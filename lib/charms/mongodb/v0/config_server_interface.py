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
from ops.charm import CharmBase, EventBase, RelationBrokenEvent
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
LIBPATCH = 4


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

        self.framework.observe(
            charm.on[self.relation_name].relation_departed,
            self.charm.check_relation_broken_or_scale_down,
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_broken, self._on_relation_broken
        )

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

    def _on_relation_broken(self, event) -> None:
        # Only relation_deparated events can check if scaling down
        departed_relation_id = event.relation.id
        if not self.charm.has_departed_run(departed_relation_id):
            logger.info(
                "Deferring, must wait for relation departed hook to decide if relation should be removed."
            )
            event.defer()
            return

        if not self.pass_hook_checks(event):
            logger.info("Skipping relation broken event: hook checks did not pass")
            return

        if not self.charm.proceed_on_broken_event(event):
            logger.info("Skipping relation broken event, broken event due to scale down")
            return

        self.charm.client_relations.oversee_users(departed_relation_id, event)

    def update_config_server_db(self, event):
        """Provides related mongos applications with new config server db."""
        if not self.pass_hook_checks(event):
            logger.info("Skipping update_config_server_db: hook checks did not pass")
            return

        config_server_db = self.generate_config_server_db()

        if not self.charm.unit.is_leader():
            return

        for relation in self.charm.model.relations[self.relation_name]:
            self.database_provides.update_relation_data(
                relation.id,
                {
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
            relations_aliases=[self.relation_name],
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
            self.database_requires.on.database_created, self._on_database_created
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_departed,
            self.charm.check_relation_broken_or_scale_down,
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_broken, self._on_relation_broken
        )

    def _on_database_created(self, event) -> None:
        if not self.charm.unit.is_leader():
            return

        logger.info("Database and user created for mongos application")
        self.charm.set_secret(Config.Relations.APP_SCOPE, Config.Secrets.USERNAME, event.username)
        self.charm.set_secret(Config.Relations.APP_SCOPE, Config.Secrets.PASSWORD, event.password)
        self.charm.share_connection_info()

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

        self.charm.unit.status = ActiveStatus()

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        # Only relation_deparated events can check if scaling down
        if not self.charm.has_departed_run(event.relation.id):
            logger.info(
                "Deferring, must wait for relation departed hook to decide if relation should be removed."
            )
            event.defer()
            return

        if not self.charm.proceed_on_broken_event(event):
            logger.info("Skipping relation broken event, broken event due to scale down")
            return

        self.charm.stop_mongos_service()
        logger.info("Stopped mongos daemon")

        if not self.charm.unit.is_leader():
            return

        logger.info("Database and user removed for mongos application")
        self.charm.remove_secret(Config.Relations.APP_SCOPE, Config.Secrets.USERNAME)
        self.charm.remove_secret(Config.Relations.APP_SCOPE, Config.Secrets.PASSWORD)
        self.charm.remove_connection_info()

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
