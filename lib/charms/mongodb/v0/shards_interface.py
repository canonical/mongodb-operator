# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage relations between config-servers and shards.

This class handles the sharing of secrets between sharded components, adding shards, and removing
shards.
"""
import logging

from charms.mongodb.v0.helpers import KEY_FILE
from charms.mongodb.v0.users import MongoDBUser, OperatorUser
from ops.charm import CharmBase
from ops.framework import Object
from ops.model import BlockedStatus, MaintenanceStatus

from config import Config

logger = logging.getLogger(__name__)


# The unique Charmhub library identifier, never change it
LIBID = "55fee8fa73364fb0a2dc16a954b2fd4a"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1
KEYFILE_KEY = "key-file"
OPERATOR_PASSWORD_KEY = "operator-password"


class ShardingProvider(Object):
    """Manage relations between the config server and the shard, on the config-server's side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.CONFIG_SERVER_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingRequirer object."""
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_joined, self._on_relation_joined
        )
        # TODO Future PR, enable shard drainage by listening for relation departed events

    def _on_relation_joined(self, event):
        """Handles providing shards with secrets and adding shards to the config server."""
        if self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info(
                "skipping relation joined event ShardingRequirer is only be executed by config-server"
            )
            return

        if not self.charm.unit.is_leader():
            return

        if not self.charm.db_initialised:
            event.defer()

        # TODO Future PR, sync tls secrets and PBM password
        self._update_relation_data(
            event.relation.id,
            {
                OPERATOR_PASSWORD_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE,
                    MongoDBUser.get_password_key_name_for_user("operator"),
                ),
                KEYFILE_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                ),
            },
        )

        # TODO Future PR, add shard to config server
        # TODO Follow up PR, handle rotating passwords

    def _update_relation_data(self, relation_id: int, data: dict) -> None:
        """Updates a set of key-value pairs in the relation.

        This function writes in the application data bag, therefore, only the leader unit can call
        it.

        Args:
            relation_id: the identifier for a particular relation.
            data: dict containing the key-value pairs
                that should be updated in the relation.
        """
        if self.charm.unit.is_leader():
            relation = self.charm.model.get_relation(self.relation_name, relation_id)
            if relation:
                relation.data[self.charm.model.app].update(data)


class ConfigServerRequirer(Object):
    """Manage relations between the config server and the shard, on the shard's side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.SHARDING_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object."""
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )

        # TODO Future PR, enable shard drainage by observing relation departed events

    def _on_relation_changed(self, event):
        """Retrieves secrets from config-server and updates them within the shard."""
        if self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info(
                "skipping relation changed event ShardingProvider is only be executed by shards"
            )
            return

        if not self.charm.db_initialised:
            event.defer()

        # shards rely on the config server for secrets
        relation_data = event.relation.data[event.app]
        self.update_keyfile(key_file_contents=relation_data.get(KEYFILE_KEY))
        self.update_operator_password(new_password=relation_data.get(OPERATOR_PASSWORD_KEY))

        self.charm.unit.status = MaintenanceStatus("Adding shard to config-server")

        # TODO future PR, leader unit verifies shard was added to cluster
        if not self.charm.unit.is_leader():
            return

    def update_operator_password(self, new_password: str) -> None:
        """Updates the password for the operator user.

        Raises:
            RetryError
        """
        current_password = (
            self.charm.get_secret(
                Config.Relations.APP_SCOPE, MongoDBUser.get_password_key_name_for_user("operator")
            ),
        )

        if not new_password or new_password == current_password or not self.charm.unit.is_leader():
            return

        self.charm.set_secret(
            Config.Relations.APP_SCOPE,
            MongoDBUser.get_password_key_name_for_user(OperatorUser.get_username()),
            new_password,
        )

    def update_keyfile(self, key_file_contents: str) -> None:
        """Updates keyfile on all units."""
        if not key_file_contents:
            return

        # put keyfile on the machine with appropriate permissions
        self.charm.push_file_to_unit(
            parent_dir=Config.MONGOD_CONF_DIR, file_name=KEY_FILE, file_contents=key_file_contents
        )

        # when the contents of the keyfile change, we must restart the service
        self.charm.restart_mongod_service()

        if not self.charm.unit.is_leader():
            return

        self.charm.set_secret(
            Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME, key_file_contents
        )
