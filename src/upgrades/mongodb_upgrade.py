# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling MongoDB in-place upgrades."""

import logging
import secrets
import string
from typing import List, Optional, Tuple

from charms.mongodb.v1.mongodb import MongoConfiguration, MongoDBConnection
from charms.mongodb.v1.mongos import (
    BalancerNotEnabledError,
    MongoConfiguration,
    MongosConnection,
)
from ops.charm import ActionEvent, CharmBase
from ops.framework import EventBase, EventSource, Object
from ops.model import ActiveStatus, BlockedStatus
from pymongo.errors import OperationFailure, PyMongoError, ServerSelectionTimeoutError
from tenacity import RetryError, Retrying, retry, stop_after_attempt, wait_fixed

from config import Config
from upgrades import machine_upgrade, upgrade

logger = logging.getLogger(__name__)


WRITE_KEY = "write_value"
ROLLBACK_INSTRUCTIONS = "To rollback, `juju refresh` to the previous revision"
SHARD_NAME_INDEX = "_id"


# BEGIN: Exceptions
class FailedToElectNewPrimaryError(Exception):
    """Raised when a new primary isn't elected after stepping down."""


class ClusterNotHealthyError(Exception):
    """Raised when the cluster is not healthy."""


class BalancerStillRunningError(Exception):
    """Raised when the balancer is still running after stopping it."""


# END: Exceptions


class _PostUpgradeCheckMongoDB(EventBase):
    """Run post upgrade check on MongoDB to verify that the cluster is healhty."""

    def __init__(self, handle):
        super().__init__(handle)


class MongoDBUpgrade(Object):
    """Handlers for upgrade events."""

    post_app_upgrade_event = EventSource(_PostUpgradeCheckMongoDB)
    post_cluster_upgrade_event = EventSource(_PostUpgradeCheckMongoDB)

    def __init__(self, charm: CharmBase):
        self.charm = charm
        super().__init__(charm, upgrade.PEER_RELATION_ENDPOINT_NAME)
        self.framework.observe(
            charm.on[upgrade.PRECHECK_ACTION_NAME].action, self._on_pre_upgrade_check_action
        )

        self.framework.observe(
            charm.on[upgrade.PEER_RELATION_ENDPOINT_NAME].relation_created,
            self._on_upgrade_peer_relation_created,
        )
        self.framework.observe(
            charm.on[upgrade.PEER_RELATION_ENDPOINT_NAME].relation_changed, self._reconcile_upgrade
        )
        self.framework.observe(charm.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(
            charm.on[upgrade.RESUME_ACTION_NAME].action, self._on_resume_upgrade_action
        )
        self.framework.observe(charm.on["force-upgrade"].action, self._on_force_upgrade_action)
        self.framework.observe(self.post_app_upgrade_event, self.run_post_app_upgrade_task)
        self.framework.observe(self.post_cluster_upgrade_event, self.run_post_cluster_upgrade_task)

    # BEGIN: Event handlers
    def _on_upgrade_peer_relation_created(self, _) -> None:
        self._upgrade.save_snap_revision_after_first_install()
        if self.charm.unit.is_leader():
            if not self._upgrade.in_progress:
                # Save versions on initial start
                self._upgrade.set_versions_in_app_databag()

    def _reconcile_upgrade(self, _=None):
        """Handle upgrade events."""
        if not self._upgrade:
            logger.debug("Peer relation not available")
            return
        if not self._upgrade.versions_set:
            logger.debug("Peer relation not ready")
            return
        if self.charm.unit.is_leader() and not self._upgrade.in_progress:
            # Run before checking `self._upgrade.is_compatible` in case incompatible upgrade was
            # forced & completed on all units.
            self._upgrade.set_versions_in_app_databag()
        if not self._upgrade.is_compatible:
            self._set_upgrade_status()
            return
        if self._upgrade.unit_state is upgrade.UnitState.OUTDATED:
            try:
                authorized = self._upgrade.authorized
            except upgrade.PrecheckFailed as exception:
                self._set_upgrade_status()
                self.charm.status.set_and_share_status(exception.status)
                logger.debug(f"Set unit status to {self.unit.status}")
                logger.error(exception.status.message)
                return
            if authorized:
                self._set_upgrade_status()
                self._upgrade.upgrade_unit(charm=self.charm)
            else:
                self._set_upgrade_status()
                logger.debug("Waiting to upgrade")
                return
        self._set_upgrade_status()

    def _on_upgrade_charm(self, _):
        if self.charm.unit.is_leader():
            if not self._upgrade.in_progress:
                logger.info("Charm upgraded. MongoDB version unchanged")

            self._upgrade.upgrade_resumed = False
            self.charm.version_checker.set_version_across_all_relations()
            # Only call `_reconcile_upgrade` on leader unit to avoid race conditions with
            # `upgrade_resumed`
            self._reconcile_upgrade()

    def _on_pre_upgrade_check_action(self, event: ActionEvent) -> None:
        if not self.charm.unit.is_leader():
            message = f"Must run action on leader unit. (e.g. `juju run {self.charm.app.name}/leader {upgrade.PRECHECK_ACTION_NAME}`)"
            logger.debug(f"Pre-upgrade check event failed: {message}")
            event.fail(message)
            return
        if not self._upgrade or self._upgrade.in_progress:
            message = "Upgrade already in progress"
            logger.debug(f"Pre-upgrade check event failed: {message}")
            event.fail(message)
            return
        try:
            self._upgrade.pre_upgrade_check()
        except upgrade.PrecheckFailed as exception:
            message = (
                f"Charm is *not* ready for upgrade. Pre-upgrade check failed: {exception.message}"
            )
            logger.debug(f"Pre-upgrade check event failed: {message}")
            event.fail(message)
            return
        message = "Charm is ready for upgrade"
        event.set_results({"result": message})
        logger.debug(f"Pre-upgrade check event succeeded: {message}")

    def _on_resume_upgrade_action(self, event: ActionEvent) -> None:
        if not self.charm.unit.is_leader():
            message = f"Must run action on leader unit. (e.g. `juju run {self.charm.app.name}/leader {upgrade.RESUME_ACTION_NAME}`)"
            logger.debug(f"Resume upgrade event failed: {message}")
            event.fail(message)
            return
        if not self._upgrade or not self._upgrade.in_progress:
            message = "No upgrade in progress"
            logger.debug(f"Resume upgrade event failed: {message}")
            event.fail(message)
            return
        self._upgrade.reconcile_partition(action_event=event)

    def _on_force_upgrade_action(self, event: ActionEvent) -> None:
        if not self._upgrade or not self._upgrade.in_progress:
            message = "No upgrade in progress"
            logger.debug(f"Force upgrade event failed: {message}")
            event.fail(message)
            return
        if not self._upgrade.upgrade_resumed:
            message = f"Run `juju run {self.charm.app.name}/leader resume-upgrade` before trying to force upgrade"
            logger.debug(f"Force upgrade event failed: {message}")
            event.fail(message)
            return
        if self._upgrade.unit_state != "outdated":
            message = "Unit already upgraded"
            logger.debug(f"Force upgrade event failed: {message}")
            event.fail(message)
            return
        logger.debug("Forcing upgrade")
        event.log(f"Forcefully upgrading {self.charm.unit.name}")
        self._upgrade.upgrade_unit(charm=self.charm)
        event.set_results({"result": f"Forcefully upgraded {self.charm.unit.name}"})
        logger.debug("Forced upgrade")

    def run_post_app_upgrade_task(self, event: EventBase):
        """Runs the post upgrade check to verify that the cluster is healthy.

        By deferring before setting unit state to HEALTHY, the user will either:
            1. have to wait for the unit to resolve itself.
            2. have to run the force-upgrade action (to upgrade the next unit).
        """
        logger.debug("Running post upgrade checks to verify cluster is not broken after upgrade")
        self.run_post_upgrade_checks(event, finished_whole_cluster=False)

        if self._upgrade.unit_state != upgrade.UnitState.HEALTHY:
            return

        logger.debug("Cluster is healthy after upgrading unit %s", self.charm.unit.name)

        # Leader of config-server must wait for all shards to be upgraded before finalising the
        # upgrade.
        if not self.charm.unit.is_leader() or not self.charm.is_role(Config.Role.CONFIG_SERVER):
            return

        self.charm.upgrade.post_cluster_upgrade_event.emit()

    def run_post_cluster_upgrade_task(self, event: EventBase) -> None:
        """Waits for entire cluster to be upgraded before enabling the balancer."""
        # Leader of config-server must wait for all shards to be upgraded before finalising the
        # upgrade.
        if not self.charm.unit.is_leader() or not self.charm.is_role(Config.Role.CONFIG_SERVER):
            return

        if not self.charm.is_cluster_on_same_revision():
            logger.debug("Waiting to finalise upgrade, one or more shards need upgrade.")
            event.defer()
            return

        logger.debug(
            "Entire cluster has been upgraded, checking health of the cluster and enabling balancer."
        )
        self.run_post_upgrade_checks(event, finished_whole_cluster=True)

        try:
            with MongosConnection(self.charm.mongos_config) as mongos:
                mongos.start_and_wait_for_balancer()
        except BalancerNotEnabledError:
            logger.debug(
                "Need more time to enable the balancer after finishing the upgrade. Deferring event."
            )
            event.defer()
            return

        self.set_mongos_feature_compatibilty_version(Config.Upgrade.FEATURE_VERSION_6)

    # END: Event handlers

    # BEGIN: Helpers
    def run_post_upgrade_checks(self, event, finished_whole_cluster: bool) -> None:
        """Runs post-upgrade checks for after a shard/config-server/replset/cluster upgrade."""
        upgrade_type = "unit %s." if not finished_whole_cluster else "sharded cluster"
        try:
            self.wait_for_cluster_healthy()
        except RetryError:
            logger.error(
                "Cluster is not healthy after upgrading %s. Will retry next juju event.",
                upgrade_type,
            )
            logger.info(ROLLBACK_INSTRUCTIONS)
            self.charm.status.set_and_share_status(Config.Status.UNHEALTHY_UPGRADE)
            event.defer()
            return

        if not self.is_cluster_able_to_read_write():
            logger.error(
                "Cluster is not healthy after upgrading %s, writes not propagated throughout cluster. Deferring post upgrade check.",
                upgrade_type,
            )
            logger.info(ROLLBACK_INSTRUCTIONS)
            self.charm.status.set_and_share_status(Config.Status.UNHEALTHY_UPGRADE)
            event.defer()
            return

        if self.charm.unit.status == Config.Status.UNHEALTHY_UPGRADE:
            self.charm.status.set_and_share_status(ActiveStatus())

        self._upgrade.unit_state = upgrade.UnitState.HEALTHY

    def move_primary_to_last_upgrade_unit(self) -> None:
        """Moves the primary to last unit that gets upgraded (the unit with the lowest id).

        Raises FailedToMovePrimaryError
        """
        # no need to move primary in the scenario of one unit
        if len(self._upgrade._sorted_units) < 2:
            return

        with MongoDBConnection(self.charm.mongodb_config) as mongod:
            unit_with_lowest_id = self._upgrade._sorted_units[-1]
            if mongod.primary() == self.charm.unit_host(unit_with_lowest_id):
                logger.debug(
                    "Not moving Primary before upgrade, primary is already on the last unit to upgrade."
                )
                return

            logger.debug("Moving primary to unit: %s", unit_with_lowest_id)
            mongod.move_primary(new_primary_ip=self.charm.unit_host(unit_with_lowest_id))

    def _set_upgrade_status(self):
        # In the future if we decide to support app statuses, we will need to handle this
        # differently. Specifically ensuring that upgrade status for apps status has the lowest
        # priority
        if self.charm.unit.is_leader():
            self.charm.app.status = self._upgrade.app_status or ActiveStatus()

        # Set/clear upgrade unit status if no other unit status - upgrade status for units should
        # have the lowest priority.
        if isinstance(self.charm.unit.status, ActiveStatus) or (
            isinstance(self.charm.unit.status, BlockedStatus)
            and self.charm.unit.status.message.startswith(
                "Rollback with `juju refresh`. Pre-upgrade check failed:"
            )
        ):
            self.charm.status.set_and_share_status(
                self._upgrade.get_unit_juju_status() or ActiveStatus()
            )

    def wait_for_cluster_healthy(self) -> None:
        """Waits until the cluster is healthy after upgrading.

        After a unit restarts it can take some time for the cluster to settle.

        Raises:
            ClusterNotHealthyError.
        """
        for attempt in Retrying(stop=stop_after_attempt(10), wait=wait_fixed(1)):
            with attempt:
                if not self.is_cluster_healthy():
                    raise ClusterNotHealthyError()

    def is_cluster_healthy(self) -> bool:
        """Returns True if all nodes in the cluster/replcia set are healthy."""
        # TODO: check mongos
        with MongoDBConnection(
            self.charm.mongodb_config, "localhost", direct=True
        ) as direct_mongo:
            if not direct_mongo.is_ready:
                logger.error("Cannot proceed with upgrade. Service mongod is not running")
                return False

        # It is possible that in a previous run of post-upgrade-check, that the unit was set to
        # unhealthy. In order to check if this unit has resolved its issue, we ignore the status
        # that was set in a previous check of cluster health. Otherwise, we are stuck in an
        # infinite check of cluster health due to never being able to reset an unhealthy status.
        if not self.charm.status.is_current_unit_ready(
            ignore_unhealthy_upgrade=True
        ) or not self.charm.status.are_all_units_ready_for_upgrade(
            unit_to_ignore=self.charm.unit.name
        ):
            logger.error(
                "Cannot proceed with upgrade. Status of charm units do not show active / waiting for upgrade."
            )
            return False

        if self.charm.is_role(Config.Role.CONFIG_SERVER):
            if not self.charm.status.are_shards_status_ready_for_upgrade():
                logger.error(
                    "Cannot proceed with upgrade. Status of shard units do not show active / waiting for upgrade."
                )
                return False

        try:
            return self.are_nodes_healthy()
        except (PyMongoError, OperationFailure, ServerSelectionTimeoutError) as e:
            logger.error(
                "Cannot proceed with upgrade. Failed to check cluster health, error: %s", e
            )
            return False

    def are_nodes_healthy(self) -> bool:
        """Returns true if all nodes in the MongoDB deployment are healthy."""
        if self.charm.is_role(Config.Role.REPLICATION):
            return self.are_replica_set_nodes_healthy(self.charm.mongodb_config)

        mongos_config = self.get_cluster_mongos()
        if not self.are_shards_healthy(mongos_config):
            logger.debug(
                "One or more individual shards are not healthy - do not proceed with upgrade."
            )
            return False

        if not self.are_replicas_in_sharded_cluster_healthy(mongos_config):
            logger.debug("One or more nodes are not healthy - do not proceed with upgrade.")
            return False

        return True

    def are_replicas_in_sharded_cluster_healthy(self, mongos_config: MongoConfiguration) -> bool:
        """Returns True if all replicas in the sharded cluster are healthy."""
        # dictionary of all replica sets in the sharded cluster
        for mongodb_config in self.get_all_replica_set_configs_in_cluster():
            if not self.are_replica_set_nodes_healthy(mongodb_config):
                logger.debug(f"Replica set: {mongodb_config.replset} contains unhealthy nodes.")
                return False

        return True

    def are_shards_healthy(self, mongos_config: MongoConfiguration) -> bool:
        """Returns True if all shards in the cluster are healthy."""
        with MongosConnection(mongos_config) as mongos:
            if mongos.is_any_draining():
                logger.debug("Cluster is draining a shard, do not proceed with upgrade.")
                return False

            if not mongos.are_all_shards_aware():
                logger.debug("Not all shards are shard aware, do not proceed with upgrade.")
                return False

            # Config-Server has access to all the related shard applications.
            if self.charm.is_role(Config.Role.CONFIG_SERVER):
                relation_shards = self.charm.config_server.get_shards_from_relations()
                cluster_shards = mongos.get_shard_members()
                if len(relation_shards - cluster_shards):
                    logger.debug(
                        "Not all shards have been added/drained, do not proceed with upgrade."
                    )
                    return False

        return True

    def get_all_replica_set_configs_in_cluster(self) -> List[MongoConfiguration]:
        """Returns a list of all the mongodb_configurations for each application in the cluster."""
        mongos_config = self.get_cluster_mongos()
        mongodb_configurations = []
        if self.charm.is_role(Config.Role.SHARD):
            # the hosts of the integrated mongos application are also the config-server hosts
            config_server_hosts = self.charm.shard.get_mongos_hosts()
            mongodb_configurations = [
                self.charm.remote_mongodb_config(
                    config_server_hosts, replset=self.charm.shard.get_config_server_name()
                )
            ]
        elif self.charm.is_role(Config.Role.CONFIG_SERVER):
            mongodb_configurations = [self.charm.mongodb_config]

        with MongosConnection(mongos_config) as mongos:
            sc_status = mongos.client.admin.command("listShards")
            for shard in sc_status["shards"]:
                mongodb_configurations.append(self.get_mongodb_config_from_shard_entry(shard))

        return mongodb_configurations

    def are_replica_set_nodes_healthy(self, mongodb_config: MongoConfiguration) -> bool:
        """Returns true if all nodes in the MongoDB replica set are healthy."""
        with MongoDBConnection(mongodb_config) as mongod:
            rs_status = mongod.get_replset_status()
            rs_status = mongod.client.admin.command("replSetGetStatus")
            return not mongod.is_any_sync(rs_status)

    def is_cluster_able_to_read_write(self) -> bool:
        """Returns True if read and write is feasible for cluster."""
        if self.charm.is_role(Config.Role.REPLICATION):
            return self.is_replica_set_able_read_write()
        else:
            return self.is_sharded_cluster_able_to_read_write()

    def is_sharded_cluster_able_to_read_write(self) -> bool:
        """Returns True if possible to write all cluster shards and read from all replicas."""
        mongos_config = self.get_cluster_mongos()
        with MongosConnection(mongos_config) as mongos:
            sc_status = mongos.client.admin.command("listShards")
            for shard in sc_status["shards"]:
                # force a write to a specific shard to ensure the primary on that shard can
                # receive writes
                db_name, collection_name, write_value = self.get_random_write_and_collection()
                self.add_write_to_sharded_cluster(
                    mongos_config, db_name, collection_name, write_value
                )
                mongos.client.admin.command("movePrimary", db_name, to=shard[SHARD_NAME_INDEX])

                write_replicated = self.is_write_on_secondaries(
                    self.get_mongodb_config_from_shard_entry(shard),
                    collection_name,
                    write_value,
                    db_name,
                )

                self.clear_db_collection(mongos_config, db_name)
                if not write_replicated:
                    logger.debug(f"Test read/write to shard {shard['_id']} failed.")
                    return False

        return True

    def get_mongodb_config_from_shard_entry(self, shard_entry) -> MongoConfiguration:
        """Returns a replica set MongoConfiguration based on a shard entry from ListShards."""
        # field hosts is of the form shard01/host1:27018,host2:27018,host3:27018
        shard_hosts = shard_entry["host"].split("/")[1]
        parsed_ips = [host.split(":")[0] for host in shard_hosts.split(",")]
        return self.charm.remote_mongodb_config(parsed_ips, replset=shard_entry[SHARD_NAME_INDEX])

    def get_cluster_mongos(self) -> MongoConfiguration:
        """Return a mongos configuration for the sharded cluster."""
        return (
            self.charm.mongos_config
            if self.charm.is_role(Config.Role.CONFIG_SERVER)
            else self.charm.remote_mongos_config(self.charm.shard.get_mongos_hosts())
        )

    def is_replica_set_able_read_write(self) -> bool:
        """Returns True if is possible to write to primary and read from replicas."""
        _, collection_name, write_value = self.get_random_write_and_collection()
        self.add_write_to_replica_set(self.charm.mongodb_config, collection_name, write_value)
        write_replicated = self.is_write_on_secondaries(
            self.charm.mongodb_config, collection_name, write_value
        )
        self.clear_tmp_collection(self.charm.mongodb_config, collection_name)
        return write_replicated

    def clear_db_collection(self, mongos_config: MongoConfiguration, db_name: str) -> None:
        """Clears the temporary collection."""
        with MongoDBConnection(mongos_config) as mongos:
            mongos.client.drop_database(db_name)

    def clear_tmp_collection(
        self, mongodb_config: MongoConfiguration, collection_name: str
    ) -> None:
        """Clears the temporary collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            db.drop_collection(collection_name)

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_fixed(1),
        reraise=True,
    )
    def confirm_excepted_write_on_replica(
        self,
        host: str,
        db_name: str,
        collection: str,
        expected_write_value: str,
        secondary_config: MongoConfiguration,
    ) -> bool:
        """Returns True if the replica contains the expected write in the provided collection."""
        secondary_config.hosts = {host}
        with MongoDBConnection(secondary_config, direct=True) as direct_seconary:
            db = direct_seconary.client[db_name]
            test_collection = db[collection]
            query = test_collection.find({}, {WRITE_KEY: 1})
            if query[0][WRITE_KEY] != expected_write_value:
                raise ClusterNotHealthyError

    def get_random_write_and_collection(self) -> Tuple[str, str]:
        """Returns a tuple for a random collection name and a unique write to add to it."""
        choices = string.ascii_letters + string.digits
        collection_name = "collection_" + "".join([secrets.choice(choices) for _ in range(32)])
        write_value = "unique_write_" + "".join([secrets.choice(choices) for _ in range(16)])
        db_name = "db_name_" + "".join([secrets.choice(choices) for _ in range(32)])
        return (db_name, collection_name, write_value)

    def add_write_to_sharded_cluster(
        self, mongos_config: MongoConfiguration, db_name, collection_name, write_value
    ) -> None:
        """Adds a the provided write to the provided database with the provided collection."""
        with MongoDBConnection(mongos_config) as mongod:
            db = mongod.client[db_name]
            test_collection = db[collection_name]
            write = {WRITE_KEY: write_value}
            test_collection.insert_one(write)

    def add_write_to_replica_set(
        self, mongodb_config: MongoConfiguration, collection_name, write_value
    ) -> None:
        """Adds a the provided write to the admin database with the provided collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            test_collection = db[collection_name]
            write = {WRITE_KEY: write_value}
            test_collection.insert_one(write)

    def is_write_on_secondaries(
        self,
        mongodb_config: MongoConfiguration,
        collection_name,
        expected_write_value,
        db_name: str = "admin",
    ):
        """Returns true if the expected write."""
        for replica_ip in mongodb_config.hosts:
            try:
                self.confirm_excepted_write_on_replica(
                    replica_ip, db_name, collection_name, expected_write_value, mongodb_config
                )
            except ClusterNotHealthyError:
                # do not return False immediately - as it is
                logger.debug("Secondary with IP %s, does not contain the expected write.")
                return False

        return True

    def step_down_primary_and_wait_reelection(self) -> None:
        """Steps down the current primary and waits for a new one to be elected."""
        if len(self.charm.mongodb_config.hosts) < 2:
            logger.warning(
                "No secondaries to become primary - upgrading primary without electing a new one, expect downtime."
            )
            return

        old_primary = self.charm.primary
        with MongoDBConnection(self.charm.mongodb_config) as mongod:
            mongod.step_down_primary()

        for attempt in Retrying(stop=stop_after_attempt(30), wait=wait_fixed(1), reraise=True):
            with attempt:
                new_primary = self.charm.primary
                if new_primary == old_primary:
                    raise FailedToElectNewPrimaryError()

    def are_pre_upgrade_operations_config_server_successful(self):
        """Runs pre-upgrade operations for config-server and returns True if successful."""
        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            return False

        if not self.is_feature_compatibility_version(Config.Upgrade.FEATURE_VERSION_6):
            logger.debug(
                "Not all replicas have the expected feature compatibility: %s",
                Config.Upgrade.FEATURE_VERSION_6,
            )
            return False

        self.set_mongos_feature_compatibilty_version(Config.Upgrade.FEATURE_VERSION_6)

        # pre-upgrade sequence runs twice. Once when the user runs the pre-upgrade action and
        # again automatically on refresh (just in case the user forgot to). Disabling the balancer
        # can negatively impact the cluster, so we only disable it once the upgrade sequence has
        # begun.
        if self._upgrade.in_progress:
            try:
                self.turn_off_and_wait_for_balancer()
            except BalancerStillRunningError:
                logger.debug("Balancer is still running. Please try the pre-upgrade check later.")
                return False

        return True

    def is_feature_compatibility_version(self, expected_feature_version) -> bool:
        """Returns True if all nodes in the sharded cluster have the expected_feature_version.

        Note it is NOT sufficient to check only mongos or the individual shards. It is necessary to
        check each node according to MongoDB upgrade docs.
        """
        for replica_set_config in self.get_all_replica_set_configs_in_cluster():
            for single_host in replica_set_config.hosts:
                single_replica_config = self.charm.remote_mongodb_config(
                    single_host, replset=replica_set_config.replset, standalone=True
                )
                with MongoDBConnection(single_replica_config) as mongod:
                    version = mongod.client.admin.command(
                        ({"getParameter": 1, "featureCompatibilityVersion": 1})
                    )
                    if (
                        version["featureCompatibilityVersion"]["version"]
                        != expected_feature_version
                    ):
                        return False

        return True

    def set_mongos_feature_compatibilty_version(self, feature_version) -> None:
        """Sets the mongos feature compatibility version."""
        with MongosConnection(self.charm.mongos_config) as mongos:
            mongos.client.admin.command("setFeatureCompatibilityVersion", feature_version)

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_fixed(1),
        reraise=True,
    )
    def turn_off_and_wait_for_balancer(self):
        """Sends the stop command to the balancer and wait for it to stop running."""
        with MongosConnection(self.charm.mongos_config) as mongos:
            mongos.client.admin.command("balancerStop")
            balancer_state = mongos.client.admin.command("balancerStatus")
            if balancer_state["mode"] != "off":
                raise BalancerStillRunningError("balancer is still Running.")

    # END: helpers

    # BEGIN: properties
    @property
    def _upgrade(self) -> Optional[machine_upgrade.Upgrade]:
        try:
            return machine_upgrade.Upgrade(self.charm)
        except upgrade.PeerRelationNotReady:
            pass

    # END: properties
