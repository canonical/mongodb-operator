# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage relations between config-servers and shards.

This class handles the sharing of secrets between sharded components, adding shards, and removing
shards.
"""
import json
import logging

from charms.mongodb.v1.helpers import add_args_to_env, get_mongos_args
from charms.mongodb.v1.mongos import MongosConnection
from ops.charm import CharmBase, EventBase
from ops.framework import Object
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus

from config import Config

logger = logging.getLogger(__name__)
KEYFILE_KEY = "key-file"
KEY_FILE = "keyFile"
HOSTS_KEY = "host"
CONFIG_SERVER_DB_KEY = "config-server-db"
MONGOS_SOCKET_URI_FMT = "%2Fvar%2Fsnap%2Fcharmed-mongodb%2Fcommon%2Fvar%2Fmongodb-27018.sock"

# The unique Charmhub library identifier, never change it
LIBID = "58ad1ccca4974932ba22b97781b9b2a0"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2


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
        # TODO Future PRs handle changing of units/passwords to be propagated to mongos

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

    def _on_relation_joined(self, event) -> None:
        """Handles providing mongos with KeyFile and hosts."""
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation joined event: hook checks did not pass")
            return

        config_server_db = self.generate_config_server_db()

        # TODO Future PR, use secrets
        self._update_relation_data(
            event.relation.id,
            {
                KEYFILE_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                ),
                CONFIG_SERVER_DB_KEY: config_server_db,
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

    def generate_config_server_db(self) -> str:
        """Generates the config server database for mongos to connect to."""
        replica_set_name = self.charm.app.name
        hosts = []
        for host in self.charm._unit_ips:
            hosts.append(f"{host}:{Config.MONGODB_PORT}")

        hosts = ",".join(hosts)
        return f"{replica_set_name}/{hosts}"


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

    def _on_relation_changed(self, event) -> None:
        """Starts/restarts monogs with config server information."""
        relation_data = event.relation.data[event.app]
        if not relation_data.get(KEYFILE_KEY) or not relation_data.get(CONFIG_SERVER_DB_KEY):
            event.defer()
            self.charm.unit.status = WaitingStatus("Waiting for secrets from config-server")
            return

        updated_keyfile = self.update_keyfile(key_file_contents=relation_data.get(KEYFILE_KEY))
        updated_config = self.update_config_server_db(
            config_server_db=relation_data.get(CONFIG_SERVER_DB_KEY)
        )

        # avoid restarting mongos when possible
        if not updated_keyfile and not updated_config and self.is_mongos_running():
            return

        # mongos is not available until it is using new secrets
        logger.info("Restarting mongos with new secrets")
        self.charm.unit.status = MaintenanceStatus("starting mongos")
        self.charm.restart_mongos_service()

        # restart on high loaded databases can be very slow (e.g. up to 10-20 minutes).
        if not self.is_mongos_running():
            logger.info("mongos has not started, deferring")
            self.charm.unit.status = WaitingStatus("Waiting for mongos to start")
            event.defer()
            return

        # TODO: Follow up PR. Add a user for mongos once it has been started
        self.charm.unit.status = ActiveStatus()

    def is_mongos_running(self) -> bool:
        """Returns true if mongos service is running."""
        with MongosConnection(None, f"mongodb://{MONGOS_SOCKET_URI_FMT}") as mongo:
            return mongo.is_ready

    def update_config_server_db(self, config_server_db) -> bool:
        """Updates config server str when necessary."""
        if self.charm.config_server_db == config_server_db:
            return False

        mongos_config = self.charm.mongos_config
        mongos_start_args = get_mongos_args(
            mongos_config, snap_install=True, config_server_db=config_server_db
        )
        add_args_to_env("MONGOS_ARGS", mongos_start_args)
        self.charm.unit_peer_data["config_server_db"] = json.dumps(config_server_db)
        return True

    def update_keyfile(self, key_file_contents: str) -> bool:
        """Updates keyfile when necessary."""
        # keyfile is set by leader in application data, application data does not necessarily
        # match what is on the machine.
        current_key_file = self.charm.get_keyfile_contents()
        if not key_file_contents or key_file_contents == current_key_file:
            return False

        # put keyfile on the machine with appropriate permissions
        self.charm.push_file_to_unit(
            parent_dir=Config.MONGOD_CONF_DIR, file_name=KEY_FILE, file_contents=key_file_contents
        )

        if self.charm.unit.is_leader():
            self.charm.set_secret(
                Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME, key_file_contents
            )

        return True
