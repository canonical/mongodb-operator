# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage relations between config-servers and shards.

This class handles the sharing of secrets between sharded components, adding shards, and removing
shards.
"""
import logging

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseProvides,
    DatabaseRequires,
)
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
LIBPATCH = 5


class ClusterProvider(Object):
    """Manage relations between the config server and mongos router on the config-server side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.CLUSTER_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object."""
        self.relation_name = relation_name
        self.charm = charm
        self.database_provides = DatabaseProvides(self.charm, relation_name=self.relation_name)

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
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

    def _on_relation_changed(self, event) -> None:
        """Handles providing mongos with KeyFile and hosts."""
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation joined event: hook checks did not pass")
            return

        config_server_db = self.generate_config_server_db()

        # create user and set secrets for mongos relation
        self.charm.client_relations.oversee_users(None, None)

        # TODO Future PR, use secrets
        if self.charm.unit.is_leader():
            self.database_provides.update_relation_data(
                event.relation.id,
                {
                    KEYFILE_KEY: self.charm.get_secret(
                        Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                    ),
                    CONFIG_SERVER_DB_KEY: config_server_db,
                },
            )

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
        self.database_requires = DatabaseRequires(
            self.charm,
            relation_name=self.relation_name,
            database_name=self.charm.database,
            extra_user_roles=self.charm.extra_user_roles,
            additional_secret_fields=[KEYFILE_KEY],
        )

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_created,
            self.database_requires._on_relation_created_event,
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )
        # TODO Future PRs handle scale down

    def _on_relation_changed(self, event) -> None:
        """Starts/restarts monogs with config server information."""
        key_file_contents = self.database_requires.fetch_relation_field(
            event.relation.id, KEYFILE_KEY
        )
        config_server_db = self.database_requires.fetch_relation_field(
            event.relation.id, CONFIG_SERVER_DB_KEY
        )
        if not key_file_contents or not config_server_db:
            event.defer()
            self.charm.unit.status = WaitingStatus("Waiting for secrets from config-server")
            return

        updated_keyfile = self.update_keyfile(key_file_contents=key_file_contents)
        updated_config = self.update_config_server_db(config_server_db=config_server_db)

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

        self.charm.share_uri()
        self.charm.unit.status = ActiveStatus()

    # BEGIN: helper functions

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

    # END: helper functions