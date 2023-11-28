# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage relations between config-servers and shards.

This class handles the sharing of secrets between sharded components, adding shards, and removing
shards.
"""
import logging

from ops.charm import CharmBase, EventBase
from ops.framework import Object
from ops.model import WaitingStatus

from config import Config

logger = logging.getLogger(__name__)
KEYFILE_KEY = "key-file"
KEY_FILE = "keyFile"
HOSTS_KEY = "host"
CONFIG_SERVER_URI_KEY = "config-server-uri"

# The unique Charmhub library identifier, never change it
LIBID = "58ad1ccca4974932ba22b97781b9b2a0"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


class ClusterProvider(Object):
    """Manage relations between the config server and mongos router on the config-server side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.CLUSTER_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object."""
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_joined, self._on_relation_joined
        )

        # TODO Future PRs handle scale down

    def pass_hook_checks(self, event: EventBase) -> bool:
        """Runs the pre-hooks checks for ClusterProvider, returns True if all pass."""
        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info(
                "Skipping %s. ShardingProvider is only be executed by config-server", type(event)
            )
            return False

        if not self.charm.unit.is_leader():
            return False

        if not self.charm.db_initialised:
            logger.info("Deferring %s. db is not initialised.", type(event))
            event.defer()
            return False

        return True

    def _on_relation_joined(self, event):
        """Handles providing mongos with KeyFile and hosts."""
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation joined event: hook checks did not pass")
            return

        # TODO Future PR, provide URI
        # TODO Future PR, use secrets
        self._update_relation_data(
            event.relation.id,
            {
                KEYFILE_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                ),
            },
        )

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


class ClusterRequirer(Object):
    """Manage relations between the config server and mongos router on the mongos side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.CLUSTER_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object."""
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )
        # TODO Future PRs handle scale down

    def _on_relation_changed(self, event):
        """Starts/restarts monogs with config server information."""
        relation_data = event.relation.data[event.app]
        if not relation_data.get(KEYFILE_KEY):
            event.defer()
            self.charm.unit.status = WaitingStatus("Waiting for secrets from config-server")
            return

        self.update_keyfile(key_file_contents=relation_data.get(KEYFILE_KEY))

        # TODO: Follow up PR. Start mongos with the config-server URI
        # TODO: Follow up PR. Add a user for mongos once it has been started

    def update_keyfile(self, key_file_contents: str) -> None:
        """Updates keyfile on all units."""
        # keyfile is set by leader in application data, application data does not necessarily
        # match what is on the machine.
        current_key_file = self.charm.get_keyfile_contents()
        if not key_file_contents or key_file_contents == current_key_file:
            return

        # put keyfile on the machine with appropriate permissions
        self.charm.push_file_to_unit(
            parent_dir=Config.MONGOD_CONF_DIR, file_name=KEY_FILE, file_contents=key_file_contents
        )

        if not self.charm.unit.is_leader():
            return

        self.charm.set_secret(
            Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME, key_file_contents
        )
