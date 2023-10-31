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
from charms.mongodb.v1.users import MongoDBUser, OperatorUser
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
LIBPATCH = 2
KEYFILE_KEY = "key-file"
HOSTS_KEY = "host"
OPERATOR_PASSWORD_KEY = MongoDBUser.get_password_key_name_for_user(OperatorUser.get_username())
FORBIDDEN_REMOVAL_ERR_CODE = 20


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
        self._update_relation_data(
            event.relation.id,
            {
                OPERATOR_PASSWORD_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE,
                    OPERATOR_PASSWORD_KEY,
                ),
                KEYFILE_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                ),
                HOSTS_KEY: json.dumps(self.charm._unit_ips),
            },
        )

    def pass_hook_checks(self, event: EventBase) -> bool:
        """Runs the pre-hooks checks for ShardingProvider, returns True if all pass."""
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

        if not self.charm.db_initialised:
            logger.info("Deferring %s. db is not initialised.", type(event))
            event.defer()
            return False

        # adding/removing shards while a backup/restore is in progress can be disastrous
        pbm_status = self.charm.backups.get_pbm_status()
        if isinstance(pbm_status, MaintenanceStatus):
            logger.info("Cannot add/remove shards while a backup/restore is in progress.")
            event.defer()
            return False

        return True

    def _proceed_on_broken_event(self, event) -> int:
        """Returns relation_id if relation broken event occurred due to a removed relation."""
        departed_relation_id = None

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
                "Relation broken event occurring due to scale down, do not proceed to remove users."
            )
            return

        return departed_relation_id

    def _on_relation_event(self, event):
        """Handles adding and removing of shards.

        Updating of shards is done automatically via MongoDB change-streams.
        """
        if not self.pass_hook_checks(event):
            logger.info("Skipping relation event: hook checks did not pass")
            return

        departed_relation_id = None
        if isinstance(event, RelationBrokenEvent):
            departed_relation_id = self._proceed_on_broken_event(event)
            if not departed_relation_id:
                return

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
        except BalancerNotEnabledError:
            logger.error("Deferring on _relation_broken_event, balancer is not enabled.")
            event.defer()
            return
        except (PyMongoError, NotReadyError) as e:
            logger.error("Deferring _on_relation_event for shards interface since: error=%r", e)
            event.defer()
            return

    def add_shards(self, departed_shard_id):
        """Adds shards to cluster.

        raises: PyMongoError
        """
        with MongosConnection(self.charm.mongos_config) as mongo:
            cluster_shards = mongo.get_shard_members()
            relation_shards = self._get_shards_from_relations(departed_shard_id)

            # TODO Future PR, limit number of shards add at a time, based on the number of
            # replicas in the primary shard
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
                    logger.error("Failed to add shard %s to the config server, error=%r", shard, e)
                    raise

        self.charm.unit.status = ActiveStatus("")

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

    def get_config_server_status(self):
        """TODO: Implement this function in a separate PR."""
        return None

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
        if self.charm.unit.is_leader():
            self.charm.app_peer_data["drained"] = json.dumps(False)

        self.charm.unit.status = MaintenanceStatus("Adding shard to config-server")

        # shards rely on the config server for secrets
        relation_data = event.relation.data[event.app]
        if not relation_data.get(KEYFILE_KEY):
            event.defer()
            self.charm.unit.status = WaitingStatus("Waiting for secrets from config-server")
            return

        self.update_keyfile(key_file_contents=relation_data.get(KEYFILE_KEY))

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
        if not relation_data.get(OPERATOR_PASSWORD_KEY):
            event.defer()
            self.charm.unit.status = WaitingStatus("Waiting for secrets from config-server")
            return

        try:
            self.update_operator_password(new_password=relation_data.get(OPERATOR_PASSWORD_KEY))
        except RetryError:
            self.charm.unit.status = BlockedStatus("Shard not added to config-server")
            logger.error(
                "Shard could not be added to config server, failed to set operator password."
            )
            event.defer()
            return

        self.charm.app_peer_data["added_to_cluster"] = json.dumps(True)

    def pass_hook_checks(self, event):
        """Runs the pre-hooks checks for ConfigServerRequirer, returns True if all pass."""
        if not self.charm.is_relation_feasible(self.relation_name):
            logger.info("Skipping event %s , relation not feasible.", type(event))
            return False

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info("skipping %s is only be executed by shards", type(event))
            return False

        if not self.charm.db_initialised:
            logger.info("Deferring %s. db is not initialised.", type(event))
            event.defer()
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
        # mongos hosts must be retrieved via relation data, as relation.units are not available in
        # broken
        mongos_hosts = json.loads(event.relation.data[event.relation.app].get(HOSTS_KEY))
        self.wait_for_draining(mongos_hosts)

        self.charm.unit.status = ActiveStatus("Shard drained from cluster, ready for removal")

        if self.charm.unit.is_leader():
            self.charm.app_peer_data["added_to_cluster"] = json.dumps(False)

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
                if self.charm.unit.is_leader():
                    self.charm.app_peer_data["drained"] = json.dumps(True)

                break

    def get_shard_status(self) -> Optional[StatusBase]:
        """Returns the current status of the shard.

        Note: No need to report if currently draining, since that check block other hooks from
        executing.
        """
        if not self.charm.is_role(Config.Role.SHARD):
            logger.info("skipping status check, charm is not running as a shard")
            return None

        if not self.charm.db_initialised:
            logger.info("No status for shard to report, waiting for db to be initialised.")
            return None

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

        config_server_name = self.get_related_config_server()
        return ActiveStatus(f"Shard connected to config-server: {config_server_name}")

    def drained(self, mongos_hosts: Set[str], shard_name: str) -> bool:
        """Returns whether a shard has been drained from the cluster.

        Raises:
            ConfigurationError, OperationFailure, ShardNotInClusterError,
            ShardNotPlannedForRemovalError
        """
        if not self.charm.is_role(Config.Role.SHARD):
            logger.info("Component %s is not a shard, has no draining status.", self.charm.role)
            return False

        if not self.charm.unit.is_leader():
            # if "drained" hasn't been set by leader, then assume it hasn't be drained.
            return json.dumps(self.charm.app_peer_data.get("drained", False))

        with MongosConnection(self.charm.remote_mongos_config(set(mongos_hosts))) as mongo:
            # a shard is "drained" if it is NO LONGER draining.
            draining = mongo._is_shard_draining(shard_name)
            drained = not draining

            self.charm.app_peer_data["drained"] = json.dumps(drained)
            return drained

    def update_operator_password(self, new_password: str) -> None:
        """Updates the password for the operator user.

        Raises:
            RetryError
        """
        if not new_password or not self.charm.unit.is_leader():
            return

        current_password = (
            self.charm.get_secret(
                Config.Relations.APP_SCOPE,
                OPERATOR_PASSWORD_KEY,
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
            OPERATOR_PASSWORD_KEY,
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

        self.charm.remote_mongos_config(set(mongos_hosts))
        config = self.charm.remote_mongos_config(set(mongos_hosts))

        # use a URI that is not dependent on the operator password, as we are not guaranteed that
        # the shard has received the password yet.
        uri = f"mongodb://{','.join(mongos_hosts)}"
        with MongosConnection(config, uri) as mongo:
            return mongo.is_ready

    def _is_added_to_cluster(self) -> bool:
        """Returns True if the shard has been added to the cluster."""
        if "added_to_cluster" not in self.charm.app_peer_data:
            return False

        return json.loads(self.charm.app_peer_data.get("added_to_cluster"))

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
