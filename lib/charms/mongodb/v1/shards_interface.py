# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage relations between config-servers and shards.

This class handles the sharing of secrets between sharded components, adding shards, and removing
shards.
"""
import json
import logging
import time
from typing import List, Optional, Set

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseProvides,
    DatabaseRequires,
)
from charms.mongodb.v0.mongodb import (
    MongoDBConnection,
    NotReadyError,
    OperationFailure,
    PyMongoError,
)
from charms.mongodb.v1.helpers import KEY_FILE
from charms.mongodb.v1.mongodb_provider import LEGACY_REL_NAME, REL_NAME
from charms.mongodb.v1.mongos import (
    BalancerNotEnabledError,
    MongosConnection,
    NotDrainedError,
    ShardNotInClusterError,
    ShardNotPlannedForRemovalError,
)
from charms.mongodb.v1.users import BackupUser, MongoDBUser, OperatorUser
from ops.charm import CharmBase, EventBase, RelationBrokenEvent
from ops.framework import Object
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    StatusBase,
    WaitingStatus,
)
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from config import Config

logger = logging.getLogger(__name__)


# The unique Charmhub library identifier, never change it
LIBID = "55fee8fa73364fb0a2dc16a954b2fd4a"

# Increment this major API version when introducing breaking changes
LIBAPI = 1

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 8
KEYFILE_KEY = "key-file"
HOSTS_KEY = "host"
OPERATOR_PASSWORD_KEY = MongoDBUser.get_password_key_name_for_user(OperatorUser.get_username())
BACKUP_PASSWORD_KEY = MongoDBUser.get_password_key_name_for_user(BackupUser.get_username())
FORBIDDEN_REMOVAL_ERR_CODE = 20
AUTH_FAILED_CODE = 18


class ShardAuthError(Exception):
    """Raised when a shard doesn't have the same auth as the config server."""

    def __init__(self, shard: str):
        self.shard = shard


class RemoveLastShardError(Exception):
    """Raised when there is an attempt to remove the last shard in the cluster."""


class ShardingProvider(Object):
    """Manage relations between the config server and the shard, on the config-server's side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.CONFIG_SERVER_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object."""
        self.relation_name = relation_name
        self.charm = charm
        self.database_provides = DatabaseProvides(self.charm, relation_name=self.relation_name)

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_joined, self._on_relation_joined
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_departed,
            self.charm.check_relation_broken_or_scale_down,
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_event
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_broken, self._on_relation_event
        )

        # TODO Future PR: handle self healing when all IP addresses of a shard changes and we have
        # to manually update mongos

    def _on_relation_joined(self, event):
        """Handles providing shards with secrets and adding shards to the config server."""
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation joined event: hook checks did not pass")
            return

        # TODO Future PR, sync tls secrets and PBM password

        self.database_provides.update_relation_data(
            event.relation.id,
            {
                OPERATOR_PASSWORD_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE,
                    OPERATOR_PASSWORD_KEY,
                ),
                BACKUP_PASSWORD_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE,
                    BACKUP_PASSWORD_KEY,
                ),
                KEYFILE_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                ),
                HOSTS_KEY: json.dumps(self.charm._unit_ips),
            },
        )

    def pass_hook_checks(self, event: EventBase) -> bool:
        """Runs the pre-hooks checks for ShardingProvider, returns True if all pass."""
        if not self.charm.db_initialised:
            logger.info("Deferring %s. db is not initialised.", type(event))
            event.defer()
            return False

        if not self.charm.is_relation_feasible(self.relation_name):
            logger.info("Skipping event %s , relation not feasible.", type(event))
            return False

        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info(
                "Skipping %s. ShardingProvider is only be executed by config-server", type(event)
            )
            return False

        if not self.charm.unit.is_leader():
            return False

        # adding/removing shards while a backup/restore is in progress can be disastrous
        pbm_status = self.charm.backups.get_pbm_status()
        if isinstance(pbm_status, MaintenanceStatus):
            logger.info("Cannot add/remove shards while a backup/restore is in progress.")
            event.defer()
            return False

        if isinstance(event, RelationBrokenEvent):
            if not self.charm.has_departed_run(event.relation.id):
                logger.info(
                    "Deferring, must wait for relation departed hook to decide if relation should be removed."
                )
                event.defer()
                return False

            if not self.charm.proceed_on_broken_event(event):
                return False

        return True

    def _on_relation_event(self, event):
        """Handles adding and removing of shards.

        Updating of shards is done automatically via MongoDB change-streams.
        """
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation event: hook checks did not pass")
            return

        departed_relation_id = None
        if isinstance(event, RelationBrokenEvent):
            departed_relation_id = event.relation.id

        try:
            logger.info("Adding/Removing shards not present in cluster.")
            self.add_shards(departed_relation_id)
            self.remove_shards(departed_relation_id)
        except NotDrainedError:
            # it is necessary to removeShard multiple times for the shard to be removed.
            logger.info(
                "Shard is still present in the cluster after removal, will defer and remove again."
            )
            event.defer()
            return
        except OperationFailure as e:
            if e.code == FORBIDDEN_REMOVAL_ERR_CODE:
                # TODO Future PR, allow removal of last shards that have no data. This will be
                # tricky since we are not allowed to update the mongos config in this way.
                logger.error(
                    "Cannot not remove the last shard from cluster, this is forbidden by mongos."
                )
                # we should not lose connection with the shard, prevent other hooks from executing.
                raise RemoveLastShardError()

            logger.error("Deferring _on_relation_event for shards interface since: error=%r", e)
            event.defer()
        except ShardAuthError as e:
            self.charm.unit.status = WaitingStatus(f"Waiting for {e.shard} to sync credentials.")
            event.defer()
            return
        except (PyMongoError, NotReadyError, BalancerNotEnabledError) as e:
            logger.error("Deferring _on_relation_event for shards interface since: error=%r", e)
            event.defer()
            return

    def add_shards(self, departed_shard_id):
        """Adds shards to cluster.

        raises: PyMongoError
        """
        failed_to_add_shard = None
        with MongosConnection(self.charm.mongos_config) as mongo:
            cluster_shards = mongo.get_shard_members()
            relation_shards = self._get_shards_from_relations(departed_shard_id)
            for shard in relation_shards - cluster_shards:
                try:
                    shard_hosts = self._get_shard_hosts(shard)
                    if not len(shard_hosts):
                        logger.info("host info for shard %s not yet added, skipping", shard)
                        continue

                    self.charm.unit.status = MaintenanceStatus(
                        f"Adding shard {shard} to config-server"
                    )
                    logger.info("Adding shard: %s ", shard)
                    mongo.add_shard(shard, shard_hosts)
                except PyMongoError as e:
                    # raise exception after trying to add the remaining shards, as to not prevent
                    # adding other shards
                    logger.error("Failed to add shard %s to the config server, error=%r", shard, e)
                    failed_to_add_shard = (e, shard)

        if not failed_to_add_shard:
            self.charm.unit.status = ActiveStatus("")
            return

        (error, shard) = failed_to_add_shard

        # Sometimes it can take up to 20 minutes for the shard to be restarted with the same auth
        # as the config server.
        if error.code == AUTH_FAILED_CODE:
            logger.error(f"{shard} shard does not have the same auth as the config server.")
            raise ShardAuthError(shard)

        logger.error(f"Failed to add {shard} to cluster")
        raise error

    def remove_shards(self, departed_shard_id):
        """Removes shards from cluster.

        raises: PyMongoError, NotReadyError
        """
        retry_removal = False
        with MongosConnection(self.charm.mongos_config) as mongo:
            cluster_shards = mongo.get_shard_members()
            relation_shards = self._get_shards_from_relations(departed_shard_id)

            for shard in cluster_shards - relation_shards:
                try:
                    self.charm.unit.status = MaintenanceStatus(f"Draining shard {shard}")
                    logger.info("Attempting to removing shard: %s", shard)
                    mongo.remove_shard(shard)
                except NotReadyError:
                    logger.info("Unable to remove shard: %s another shard is draining", shard)
                    # to guarantee that shard that the currently draining shard, gets re-processed,
                    # do not raise immediately, instead at the end of removal processing.
                    retry_removal = True
                except ShardNotInClusterError:
                    logger.info(
                        "Shard to remove is not in sharded cluster. It has been successfully removed."
                    )

        if retry_removal:
            raise ShardNotInClusterError

    def update_credentials(self, key: str, value: str) -> None:
        """Sends new credentials, for a key value pair across all shards."""
        for relation in self.charm.model.relations[self.relation_name]:
            self._update_relation_data(relation.id, {key: value})

    def update_mongos_hosts(self):
        """Updates the hosts for mongos on the relation data."""
        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info("Skipping, ShardingProvider is only be executed by config-server")
            return

        for relation in self.charm.model.relations[self.relation_name]:
            self._update_relation_data(relation.id, {HOSTS_KEY: json.dumps(self.charm._unit_ips)})

    def get_config_server_status(self) -> Optional[StatusBase]:
        """Returns the current status of the config-server."""
        if self.skip_config_server_status():
            return None

        if (
            self.charm.is_role(Config.Role.REPLICATION)
            and self.model.relations[Config.Relations.CONFIG_SERVER_RELATIONS_NAME]
        ):
            return BlockedStatus("sharding interface cannot be used by replicas")

        if self.model.relations[LEGACY_REL_NAME]:
            return BlockedStatus(f"relation {LEGACY_REL_NAME} to shard not supported.")

        if self.model.relations[REL_NAME]:
            return BlockedStatus(f"relation {REL_NAME} to shard not supported.")

        if not self.is_mongos_running():
            return BlockedStatus("Internal mongos is not running.")

        shard_draining = self.get_draining_shards()
        if shard_draining:
            shard_draining = ",".join(shard_draining)
            return MaintenanceStatus(f"Draining shard {shard_draining}")

        if not self.model.relations[self.relation_name]:
            return BlockedStatus("missing relation to shard(s)")

        unreachable_shards = self.get_unreachable_shards()
        if unreachable_shards:
            unreachable_shards = ", ".join(unreachable_shards)
            return BlockedStatus(f"shards {unreachable_shards} are unreachable.")

        return ActiveStatus()

    def skip_config_server_status(self) -> bool:
        """Returns true if the status check should be skipped."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.info("skipping config server status check, charm is  running as a shard")
            return True

        if not self.charm.db_initialised:
            logger.info("No status for shard to report, waiting for db to be initialised.")
            return True

        if (
            self.charm.is_role(Config.Role.REPLICATION)
            and not self.model.relations[Config.Relations.CONFIG_SERVER_RELATIONS_NAME]
        ):
            return True

        return False

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

    def _get_shards_from_relations(self, departed_shard_id: Optional[int]):
        """Returns a list of the shards related to the config-server."""
        relations = self.model.relations[self.relation_name]
        return set(
            [
                self._get_shard_name_from_relation(relation)
                for relation in relations
                if relation.id != departed_shard_id
            ]
        )

    def _get_shard_hosts(self, shard_name) -> List[str]:
        """Retrieves the hosts for a specified shard."""
        relations = self.model.relations[self.relation_name]
        for relation in relations:
            if self._get_shard_name_from_relation(relation) == shard_name:
                hosts = []
                for unit in relation.units:
                    hosts.append(relation.data[unit].get("private-address"))

                return hosts

    def _get_shard_name_from_relation(self, relation):
        """Returns the name of a shard for a specified relation."""
        return relation.app.name

    def has_shards(self) -> bool:
        """Returns True if currently related to shards."""
        return len(self.charm.model.relations[self.relation_name]) > 0

    def get_related_shards(self) -> List[str]:
        """Returns a list of related shards."""
        return [rel.app.name for rel in self.charm.model.relations[self.relation_name]]

    def get_unreachable_shards(self) -> List[str]:
        """Returns a list of unreable shard hosts."""
        unreachable_hosts = []
        if not self.model.relations[self.relation_name]:
            logger.info("shards are not reachable, none related to config-sever")
            return unreachable_hosts

        for shard_name in self.get_related_shards():
            shard_hosts = self._get_shard_hosts(shard_name)
            if not shard_hosts:
                return unreachable_hosts

            # use a URI that is not dependent on the operator password, as we are not guaranteed
            # that the shard has received the password yet.
            uri = f"mongodb://{','.join(shard_hosts)}"
            with MongoDBConnection(None, uri) as mongo:
                if not mongo.is_ready:
                    unreachable_hosts.append(shard_name)

        return unreachable_hosts

    def is_mongos_running(self) -> bool:
        """Returns true if mongos service is running."""
        mongos_hosts = ",".join(self.charm._unit_ips)
        uri = f"mongodb://{mongos_hosts}"
        with MongosConnection(None, uri) as mongo:
            return mongo.is_ready

    def get_draining_shards(self) -> List[str]:
        """Returns the shard that is currently draining."""
        with MongosConnection(self.charm.mongos_config) as mongo:
            draining_shards = mongo.get_draining_shards()

            # in theory, this should always be a list of one. But if something has gone wrong we
            # should take note and log it
            if len(draining_shards) > 1:
                logger.error("Multiple shards draining at the same time.")

            return draining_shards

    def cluster_password_synced(self) -> bool:
        """Returns True if the cluster password is synced."""
        # base case: not config-server
        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            return True

        # base case: no cluster relation
        if not self.model.relations[self.relation_name]:
            return True

        try:
            # check our ability to use connect to cluster
            with MongosConnection(self.charm.mongos_config) as mongos:
                mongos.get_shard_members()
        except OperationFailure as e:
            if e.code == 18:  # Unauthorized Error - i.e. password is not in sync
                return False
            raise

        return True


class ConfigServerRequirer(Object):
    """Manage relations between the config server and the shard, on the shard's side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.SHARDING_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object."""
        self.relation_name = relation_name
        self.charm = charm
        self.database_requires = DatabaseRequires(
            self.charm,
            relation_name=self.relation_name,
            additional_secret_fields=[KEYFILE_KEY, OPERATOR_PASSWORD_KEY, BACKUP_PASSWORD_KEY],
            # a database isn't required for the relation between shards + config servers, but is a
            # requirement for using `DatabaseRequires`
            database_name="",
        )

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

    def _on_relation_changed(self, event):
        """Retrieves secrets from config-server and updates them within the shard."""
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation joined event: hook checks re not passed")
            return

        # if re-using an old shard, re-set drained flag.
        self.charm.unit_peer_data["drained"] = json.dumps(False)

        # TODO: Future PR better status message behavior
        self.charm.unit.status = MaintenanceStatus("Adding shard to config-server")

        # shards rely on the config server for secrets
        key_file_contents = self.database_requires.fetch_relation_field(
            event.relation.id, KEYFILE_KEY
        )
        if not key_file_contents:
            event.defer()
            self.charm.unit.status = WaitingStatus("Waiting for secrets from config-server")
            return

        self.update_keyfile(key_file_contents=key_file_contents)

        # restart on high loaded databases can be very slow (e.g. up to 10-20 minutes).
        with MongoDBConnection(self.charm.mongodb_config) as mongo:
            if not mongo.is_ready:
                logger.info("shard has not started yet, deferfing")
                self.charm.unit.status = WaitingStatus("Waiting for MongoDB to start")
                event.defer()
                return

        if not self.charm.unit.is_leader():
            return

        # TODO Future work, see if needed to check for all units restarted / primary elected
        operator_password = self.database_requires.fetch_relation_field(
            event.relation.id, OPERATOR_PASSWORD_KEY
        )
        backup_password = self.database_requires.fetch_relation_field(
            event.relation.id, BACKUP_PASSWORD_KEY
        )
        if not operator_password or not backup_password:
            event.defer()
            self.charm.unit.status = WaitingStatus("Waiting for secrets from config-server")
            return

        try:
            self.update_password(
                username=OperatorUser.get_username(), new_password=operator_password
            )
            self.update_password(BackupUser.get_username(), new_password=backup_password)
        except RetryError:
            self.charm.unit.status = BlockedStatus("Shard not added to config-server")
            logger.error(
                "Shard could not be added to config server, failed to set operator password."
            )
            event.defer()
            return

        # after updating the password of the backup user, restart pbm with correct password
        self.charm._connect_pbm_agent()
        self.charm.app_peer_data["mongos_hosts"] = json.dumps(self.get_mongos_hosts())

    def pass_hook_checks(self, event):
        """Runs the pre-hooks checks for ConfigServerRequirer, returns True if all pass."""
        if not self.charm.db_initialised:
            logger.info("Deferring %s. db is not initialised.", type(event))
            event.defer()
            return False

        if not self.charm.is_relation_feasible(self.relation_name):
            logger.info("Skipping event %s , relation not feasible.", type(event))
            return False

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info("skipping %s is only be executed by shards", type(event))
            return False

        # occasionally, broken events have no application, in these scenarios nothing should be
        # processed.
        if not event.relation.app:
            return False

        mongos_hosts = event.relation.data[event.relation.app].get(HOSTS_KEY, None)
        if isinstance(event, RelationBrokenEvent) and not mongos_hosts:
            logger.info("Config-server relation never set up, no need to process broken event.")
            return False

        return True

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Waits for the shard to be fully drained from the cluster."""
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation joined event: hook checks re not passed")
            return

        # Only relation_deparated events can check if scaling down
        departed_relation_id = event.relation.id
        if not self.charm.has_departed_run(departed_relation_id):
            logger.info(
                "Deferring, must wait for relation departed hook to decide if relation should be removed."
            )
            event.defer()
            return

        # check if were scaling down and add a log message
        if self.charm.is_scaling_down(event.relation.id):
            logger.info(
                "Relation broken event occurring due to scale down, do not proceed to remove shards."
            )
            return

        self.charm.unit.status = MaintenanceStatus("Draining shard from cluster")
        mongos_hosts = json.loads(self.charm.app_peer_data["mongos_hosts"])
        self.wait_for_draining(mongos_hosts)

        self.charm.unit.status = ActiveStatus("Shard drained from cluster, ready for removal")

    def wait_for_draining(self, mongos_hosts: List[str]):
        """Waits for shards to be drained from sharded cluster."""
        drained = False

        while not drained:
            try:
                # no need to continuously check and abuse resources while shard is draining
                time.sleep(60)
                drained = self.drained(mongos_hosts, self.charm.app.name)
                self.charm.unit.status = MaintenanceStatus("Draining shard from cluster")
                draining_status = (
                    "Shard is still draining" if not drained else "Shard is fully drained."
                )
                self.charm.unit.status = MaintenanceStatus("Draining shard from cluster")
                logger.debug(draining_status)
            except PyMongoError as e:
                logger.error("Error occurred while draining shard: %s", e)
                self.charm.unit.status = BlockedStatus("Failed to drain shard from cluster")
            except ShardNotPlannedForRemovalError:
                logger.info(
                    "Shard %s has not been identifies for removal. Must wait for mongos cluster-admin to remove shard."
                )
                self.charm.unit.status = WaitingStatus("Waiting for config-server to remove shard")
            except ShardNotInClusterError:
                logger.info(
                    "Shard to remove is not in sharded cluster. It has been successfully removed."
                )
                self.charm.unit_peer_data["drained"] = json.dumps(True)

                break

    def get_shard_status(self) -> Optional[StatusBase]:
        """Returns the current status of the shard.

        Note: No need to report if currently draining, since that check block other hooks from
        executing.
        """
        if self.skip_shard_status():
            return None

        if (
            self.charm.is_role(Config.Role.REPLICATION)
            and self.model.relations[Config.Relations.CONFIG_SERVER_RELATIONS_NAME]
        ):
            return BlockedStatus("sharding interface cannot be used by replicas")

        if self.model.get_relation(LEGACY_REL_NAME):
            return BlockedStatus(f"relation {LEGACY_REL_NAME} to shard not supported.")

        if self.model.get_relation(REL_NAME):
            return BlockedStatus(f"relation {REL_NAME} to shard not supported.")

        if not self.model.get_relation(self.relation_name) and not self.charm.drained:
            return BlockedStatus("missing relation to config server")

        if not self.model.get_relation(self.relation_name) and self.charm.drained:
            return ActiveStatus("Shard drained from cluster, ready for removal")

        if not self._is_mongos_reachable():
            return BlockedStatus("Config server unreachable")

        if not self._is_added_to_cluster():
            return MaintenanceStatus("Adding shard to config-server")

        if not self._is_shard_aware():
            return BlockedStatus("Shard is not yet shard aware")

        return ActiveStatus()

    def skip_shard_status(self) -> bool:
        """Returns true if the status check should be skipped."""
        if self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info("skipping status check, charm is running as config-server")
            return True

        if not self.charm.db_initialised:
            logger.info("No status for shard to report, waiting for db to be initialised.")
            return True

        if (
            self.charm.is_role(Config.Role.REPLICATION)
            and not self.model.relations[Config.Relations.CONFIG_SERVER_RELATIONS_NAME]
        ):
            return True

        return False

    def drained(self, mongos_hosts: Set[str], shard_name: str) -> bool:
        """Returns whether a shard has been drained from the cluster.

        Raises:
            ConfigurationError, OperationFailure, ShardNotInClusterError,
            ShardNotPlannedForRemovalError
        """
        if not self.charm.is_role(Config.Role.SHARD):
            logger.info("Component %s is not a shard, has no draining status.", self.charm.role)
            return False

        with MongosConnection(self.charm.remote_mongos_config(set(mongos_hosts))) as mongo:
            # a shard is "drained" if it is NO LONGER draining.
            draining = mongo._is_shard_draining(shard_name)
            drained = not draining

            self.charm.unit_peer_data["drained"] = json.dumps(drained)
            return drained

    def update_password(self, username: str, new_password: str) -> None:
        """Updates the password for the given user.

        Raises:
            RetryError
        """
        if not new_password or not self.charm.unit.is_leader():
            return

        current_password = (
            self.charm.get_secret(
                Config.Relations.APP_SCOPE, MongoDBUser.get_password_key_name_for_user(username)
            ),
        )

        if new_password == current_password:
            return

        # updating operator password, usually comes after keyfile was updated, hence, the mongodb
        # service was restarted. Sometimes this requires units getting insync again.
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
            with attempt:
                # TODO, in the future use set_password from src/charm.py - this will require adding
                # a library, for exceptions used in both charm code and lib code.
                with MongoDBConnection(self.charm.mongodb_config) as mongo:
                    try:
                        mongo.set_user_password(username, new_password)
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
            MongoDBUser.get_password_key_name_for_user(username),
            new_password,
        )

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

        # when the contents of the keyfile change, we must restart the service
        self.charm.restart_mongod_service()

        if not self.charm.unit.is_leader():
            return

        self.charm.set_secret(
            Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME, key_file_contents
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

    def _is_mongos_reachable(self) -> bool:
        """Returns True if mongos is reachable."""
        if not self.model.get_relation(self.relation_name):
            logger.info("Mongos is not reachable, no relation to config-sever")
            return False

        mongos_hosts = self.get_mongos_hosts()
        if not mongos_hosts:
            return False

        config = self.charm.remote_mongos_config(set(mongos_hosts))

        # use a URI that is not dependent on the operator password, as we are not guaranteed that
        # the shard has received the password yet.
        uri = f"mongodb://{','.join(mongos_hosts)}"
        with MongosConnection(config, uri) as mongo:
            return mongo.is_ready

    def _is_added_to_cluster(self) -> bool:
        """Returns True if the shard has been added to the cluster."""
        try:
            mongos_hosts = self.get_mongos_hosts()
            with MongosConnection(self.charm.remote_mongos_config(set(mongos_hosts))) as mongo:
                cluster_shards = mongo.get_shard_members()
                return self.charm.app.name in cluster_shards
        except OperationFailure as e:
            if e.code == 13:  # Unauthorized, we are not yet connected to mongos
                return False

            raise

    def cluster_password_synced(self) -> bool:
        """Returns True if the cluster password is synced for the shard."""
        # base case: not a shard
        if not self.charm.is_role(Config.Role.SHARD):
            return True

        # base case: no cluster relation
        if not self.model.get_relation(self.relation_name):
            return True

        try:
            # check our ability to use connect to both mongos and our current replica set.
            mongos_reachable = self._is_mongos_reachable()
            with MongoDBConnection(self.charm.mongodb_config) as mongo:
                mongod_reachable = mongo.is_ready
        except OperationFailure as e:
            if e.code == 18:  # Unauthorized Error - i.e. password is not in sync
                return False
            raise

        return mongos_reachable and mongod_reachable

    def get_shard_members(self) -> List[str]:
        """Returns a list of shard members.

        Raises: PyMongoError
        """
        mongos_hosts = self.get_mongos_hosts()
        with MongosConnection(self.charm.remote_mongos_config(set(mongos_hosts))) as mongo:
            return mongo.get_shard_members()

    def _is_shard_aware(self) -> bool:
        """Returns True if shard is in cluster and shard aware."""
        if not self.model.get_relation(self.relation_name):
            logger.info(
                "Mongos is not reachable, no relation to config-sever, cannot check shard status."
            )
            return False

        mongos_hosts = self.get_mongos_hosts()
        with MongosConnection(self.charm.remote_mongos_config(set(mongos_hosts))) as mongo:
            return mongo.is_shard_aware(shard_name=self.charm.app.name)

    def has_config_server(self) -> bool:
        """Returns True if currently related to config server."""
        return len(self.charm.model.relations[self.relation_name]) > 0

    def get_related_config_server(self) -> str:
        """Returns the related config server."""
        if self.relation_name not in self.charm.model.relations:
            return None

        # metadata.yaml prevents having multiple config servers
        return self.charm.model.relations[self.relation_name][0].app.name

    def get_mongos_hosts(self) -> List[str]:
        """Returns a list of IP addresses for the mongos hosts."""
        # only one related config-server is possible
        config_server_relation = self.charm.model.relations[self.relation_name][0]
        if HOSTS_KEY not in config_server_relation.data[config_server_relation.app]:
            return

        return json.loads(config_server_relation.data[config_server_relation.app].get(HOSTS_KEY))
