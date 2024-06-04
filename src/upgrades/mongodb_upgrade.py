# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling MongoDB in-place upgrades."""

import logging
import secrets
import string
from typing import Optional, Tuple

from charms.mongodb.v0.mongodb import MongoDBConfiguration, MongoDBConnection
from ops.charm import ActionEvent, CharmBase
from ops.framework import EventBase, EventSource, Object
from ops.model import ActiveStatus, BlockedStatus
from pymongo.errors import OperationFailure, PyMongoError, ServerSelectionTimeoutError
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed

from config import Config
from upgrades import machine_upgrade, upgrade

logger = logging.getLogger(__name__)


WRITE_KEY = "write_value"
ROLLBACK_INSTRUCTIONS = "To rollback, `juju refresh` to the previous revision"
UNHEALTHY_UPGRADE = BlockedStatus("Unhealthy after upgrade.")


# BEGIN: Exceptions
class FailedToElectNewPrimaryError(Exception):
    """Raised when a new primary isn't elected after stepping down."""


class ClusterNotHealthyError(Exception):
    """Raised when the cluster is not healthy."""


# END: Exceptions


class _PostUpgradeCheckMongoDB(EventBase):
    """Run post upgrade check on MongoDB to verify that the cluster is healhty."""

    def __init__(self, handle):
        super().__init__(handle)


class MongoDBUpgrade(Object):
    """Handlers for upgrade events."""

    post_upgrade_event = EventSource(_PostUpgradeCheckMongoDB)

    def __init__(self, charm: CharmBase):
        self.charm = charm
        super().__init__(charm, upgrade.PEER_RELATION_ENDPOINT_NAME)
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
        self.framework.observe(self.post_upgrade_event, self.post_upgrade_check)

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
        if self._upgrade.unit_state == "outdated":
            if self._upgrade.authorized:
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
            # Only call `_reconcile_upgrade` on leader unit to avoid race conditions with
            # `upgrade_resumed`
            self._reconcile_upgrade()

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

    def post_upgrade_check(self, event: EventBase):
        """Runs the post upgrade check to verify that the cluster is healthy.

        By deferring before setting unit state to HEALTHY, the user will either:
            1. have to wait for the unit to resolve itself.
            2. have to run the force-upgrade action (to upgrade the next unit).
        """
        logger.debug("Running post upgrade checks to verify cluster is not broken after upgrade")

        if not self.is_cluster_healthy():
            logger.error(
                "Cluster is not healthy after upgrading unit %s, nodes are still syncing. Will retry next juju event.",
                self.charm.unit.name,
            )
            logger.info(ROLLBACK_INSTRUCTIONS)
            self.charm.unit.status = UNHEALTHY_UPGRADE
            event.defer()
            return

        if not self.is_cluster_able_to_read_write():
            logger.error(
                "Cluster is not healthy after upgrading unit %s, writes not propagated throughout cluster. Deferring post upgrade check.",
                self.charm.unit.name,
            )
            logger.info(ROLLBACK_INSTRUCTIONS)
            self.charm.unit.status = UNHEALTHY_UPGRADE
            event.defer()
            return

        if self.charm.unit.status == UNHEALTHY_UPGRADE:
            self.charm.unit.status = ActiveStatus()

        self._upgrade.unit_state = upgrade.UnitState.HEALTHY
        logger.debug("Cluster is healthy after upgrading unit %s", self.charm.unit.name)

    # END: Event handlers

    # BEGIN: Helpers
    def _set_upgrade_status(self):
        # In the future if we decide to support app statuses, we will need to handle this
        # differently. Specifically ensuring that upgrade status for apps status has the lowest
        # priority
        if self.charm.unit.is_leader():
            self.charm.app.status = self._upgrade.app_status or ActiveStatus()

        # Set/clear upgrade unit status if no other unit status - upgrade status for units should
        # have the lowest priority.
        if isinstance(self.charm.unit.status, ActiveStatus):
            self.charm.unit.status = self._upgrade.get_unit_juju_status() or ActiveStatus()

    def is_cluster_healthy(self) -> bool:
        """Returns True if all nodes in the cluster/replcia set are healthy."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.debug("Cannot run full cluster health check on shards")
            # TODO Future PR - implement cgecj healthy check for single shard
            return False

        try:
            if self.charm.is_role(Config.Role.CONFIG_SERVER):
                # TODO Future PR - implement node healthy check for sharded cluster
                return False
            if self.charm.is_role(Config.Role.REPLICATION):
                return self.are_replica_set_nodes_healthy(self.charm.mongodb_config)
        except (PyMongoError, OperationFailure, ServerSelectionTimeoutError) as e:
            logger.debug(
                "Cannot proceed with upgrade. Failed to check cluster health, error: %s", e
            )
            return False

    def are_replica_set_nodes_healthy(self, mongodb_config: MongoDBConfiguration) -> bool:
        """Returns true if all nodes in the MongoDB replica set are healthy."""
        with MongoDBConnection(mongodb_config) as mongod:
            rs_status = mongod.get_replset_status()
            rs_status = mongod.client.admin.command("replSetGetStatus")
            return not mongod.is_any_sync(rs_status)

    def is_cluster_able_to_read_write(self) -> bool:
        """Returns True if read and write is feasible for cluster."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.debug("Cannot run read/write check on shard, must run via config-server.")
            return False
        elif self.charm.is_role(Config.Role.CONFIG_SERVER):
            # TODO Future PR - implement node healthy check for sharded cluster
            pass
        else:
            return self.is_replica_set_able_read_write()

    def is_replica_set_able_read_write(self) -> bool:
        """Returns True if is possible to write to primary and read from replicas."""
        collection_name, write_value = self.get_random_write_and_collection()
        self.add_write_to_replica_set(self.charm.mongodb_config, collection_name, write_value)
        write_replicated = self.is_write_on_secondaries(
            self.charm.mongodb_config, collection_name, write_value
        )
        self.clear_tmp_collection(self.charm.mongodb_config, collection_name)
        return write_replicated

    def clear_tmp_collection(
        self, mongodb_config: MongoDBConfiguration, collection_name: str
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
        secondary_config: MongoDBConfiguration,
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
        return (collection_name, write_value)

    def add_write_to_replica_set(
        self, mongodb_config: MongoDBConfiguration, collection_name, write_value
    ) -> None:
        """Adds a the provided write to the admin database with the provided collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            test_collection = db[collection_name]
            write = {WRITE_KEY: write_value}
            test_collection.insert_one(write)

    def is_write_on_secondaries(
        self,
        mongodb_config: MongoDBConfiguration,
        collection_name,
        expected_write_value,
        db_name: str = "admin",
    ):
        """Returns true if the expected write."""
        with MongoDBConnection(mongodb_config) as mongod:
            primary_ip = mongod.primary()

        replica_ips = mongodb_config.hosts
        secondary_ips = replica_ips - set(primary_ip)
        for secondary_ip in secondary_ips:
            try:
                self.confirm_excepted_write_on_replica(
                    secondary_ip, db_name, collection_name, expected_write_value, mongodb_config
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

    # END: helpers

    # BEGIN: properties
    @property
    def _upgrade(self) -> Optional[machine_upgrade.Upgrade]:
        try:
            return machine_upgrade.Upgrade(self.charm)
        except upgrade.PeerRelationNotReady:
            pass

    # END: properties
