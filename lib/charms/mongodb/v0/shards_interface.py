"""TODO: Add a proper docstring here.
"""
from ops.charm import CharmBase
from config import Config
from ops.framework import Object
import logging

from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    SecretNotFoundError,
    Unit,
    WaitingStatus,
)

from charms.mongodb.v0.mongodb import (
    MongoDBConnection,
    NotReadyError,
    PyMongoError,
)

from charms.mongodb.v0.helpers import KEY_FILE
from charms.mongodb.v0.users import MongoDBUser, OperatorUser

logger = logging.getLogger(__name__)


# The unique Charmhub library identifier, never change it
LIBID = "55fee8fa73364fb0a2dc16a954b2fd4a"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

# TODO: add your code here! Happy coding!


class ShardingRequirer(Object):
    """TODO docstring - something about how this is used on config server side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.CONFIG_SERVER_RELATIONS_NAME
    ) -> None:
        """Constructor for MongoDBProvider object.

        Args:
            relation_name: the name of the relation
        """
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_joined, self._on_relation_joined
        )
        # TODO Future PR, enable shard drainage by listening for relation departed events

    def _on_relation_joined(self, event):
        """TODO doc string"""
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

        if "db_initialised" not in self.charm.app_peer_data:
            event.defer()

        # TODO Future PR, sync tls secrets and PBM password
        self._update_relation_data(
            event.relation.id,
            {
                "operator-password": self.charm.get_secret(
                    Config.Relations.APP_SCOPE,
                    MongoDBUser.get_password_key_name_for_user("operator"),
                ),
                "key-file": self.charm.get_secret(
                    Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                ),
            },
        )

        # TODO Future PR, add shard to config server
        # TODO Follow up PR, handle rotating passwords

    def _update_relation_data(self, relation_id: int, data: dict) -> None:
        """Updates a set of key-value pairs in the relation.

        This function writes in the application data bag, therefore,
        only the leader unit can call it.

        Args:
            relation_id: the identifier for a particular relation.
            data: dict containing the key-value pairs
                that should be updated in the relation.
        """
        if self.charm.unit.is_leader():
            relation = self.charm.model.get_relation(self.relation_name, relation_id)
            if relation:
                relation.data[self.charm.model.app].update(data)


class ShardingProvider(Object):
    """TODO docstring - something about how this is used on shard side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.SHARDING_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object.

        Args:
            relation_name: the name of the relation
        """
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )

        # TODO Future PR, enable shard drainage by listening for relation departed events

    def _on_relation_changed(self, event):
        """TODO doc string"""
        if self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info(
                "skipping relation changed event ShardingProvider is only be executed by shards"
            )
            return

        if "db_initialised" not in self.charm.app_peer_data:
            event.defer()

        # shards rely on the config server for secrets
        relation_data = event.relation.data[event.app]
        try:
            self.update_operator_password(new_password=relation_data.get("operator-password"))
        except (PyMongoError, NotReadyError):
            self.charm.unit.status = BlockedStatus("Shard not added to config-server")
            return

        self.update_keyfile(key_file_contents=relation_data.get("key-file"))

        self.charm.unit.status = MaintenanceStatus("Adding shard to config-server")

        # TODO future PR, leader unit verifies shard was added to cluster
        if not self.charm.unit.is_leader():
            return

    def update_operator_password(self, new_password: str) -> None:
        """TODO docstring

        Raises:
            PyMongoError, NotReadyError
        """
        current_password = (
            self.charm.get_secret(
                Config.Relations.APP_SCOPE, MongoDBUser.get_password_key_name_for_user("operator")
            ),
        )

        if not new_password or new_password == current_password or not self.charm.unit.is_leader():
            return

        with MongoDBConnection(self.charm.mongodb_config) as mongo:
            try:
                mongo.set_user_password(OperatorUser.get_username(), new_password)
            except NotReadyError:
                logger.error(
                    "Failed changing the password: Not all members healthy or finished initial sync."
                )
                raise
            except PyMongoError as e:
                logger.error(f"Failed changing the password: {e}")
                raise

        self.charm.set_secret(
            Config.Relations.APP_SCOPE,
            MongoDBUser.get_password_key_name_for_user(OperatorUser.get_username()),
            new_password,
        )

    def update_keyfile(self, key_file_contents: str) -> None:
        """TODO docstring"""
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
