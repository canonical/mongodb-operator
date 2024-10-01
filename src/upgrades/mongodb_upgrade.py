# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling MongoDB in-place upgrades."""

import logging

from charms.mongodb.v0.upgrade_helpers import (
    PEER_RELATION_ENDPOINT_NAME,
    PRECHECK_ACTION_NAME,
    RESUME_ACTION_NAME,
    ROLLBACK_INSTRUCTIONS,
    GenericMongoDBUpgrade,
    PeerRelationNotReady,
    PrecheckFailed,
    UnitState,
)
from charms.mongodb.v1.mongos import BalancerNotEnabledError, MongosConnection
from ops.charm import ActionEvent, CharmBase
from ops.framework import EventBase, EventSource
from ops.model import ActiveStatus, BlockedStatus
from overrides import override
from tenacity import RetryError

from config import Config
from upgrades import machine_upgrade

logger = logging.getLogger(__name__)


class _PostUpgradeCheckMongoDB(EventBase):
    """Run post upgrade check on MongoDB to verify that the cluster is healhty."""

    def __init__(self, handle):
        super().__init__(handle)


class MongoDBUpgrade(GenericMongoDBUpgrade):
    """Handlers for upgrade events."""

    post_app_upgrade_event = EventSource(_PostUpgradeCheckMongoDB)
    post_cluster_upgrade_event = EventSource(_PostUpgradeCheckMongoDB)

    def __init__(self, charm: CharmBase):
        self.charm = charm
        super().__init__(charm, PEER_RELATION_ENDPOINT_NAME)

    @override
    def _observe_events(self, charm: CharmBase) -> None:
        self.framework.observe(
            charm.on[PRECHECK_ACTION_NAME].action, self._on_pre_upgrade_check_action
        )

        self.framework.observe(
            charm.on[PEER_RELATION_ENDPOINT_NAME].relation_created,
            self._on_upgrade_peer_relation_created,
        )
        self.framework.observe(
            charm.on[PEER_RELATION_ENDPOINT_NAME].relation_changed, self._reconcile_upgrade
        )
        self.framework.observe(charm.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(charm.on[RESUME_ACTION_NAME].action, self._on_resume_upgrade_action)
        self.framework.observe(charm.on["force-upgrade"].action, self._on_force_upgrade_action)
        self.framework.observe(self.post_app_upgrade_event, self.run_post_app_upgrade_task)
        self.framework.observe(self.post_cluster_upgrade_event, self.run_post_cluster_upgrade_task)

    # BEGIN: properties
    @property
    @override
    def _upgrade(self) -> machine_upgrade.Upgrade | None:
        try:
            return machine_upgrade.Upgrade(self.charm)
        except PeerRelationNotReady:
            return None

    # END: properties

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
        if self._upgrade.unit_state is UnitState.OUTDATED:
            try:
                authorized = self._upgrade.authorized
            except PrecheckFailed as exception:
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
                logger.info("Charm refreshed. MongoDB version unchanged")

            self._upgrade.upgrade_resumed = False
            self.charm.version_checker.set_version_across_all_relations()
            # Only call `_reconcile_upgrade` on leader unit to avoid race conditions with
            # `upgrade_resumed`
            self._reconcile_upgrade()

    def _on_pre_upgrade_check_action(self, event: ActionEvent) -> None:
        if not self.charm.unit.is_leader():
            message = f"Must run action on leader unit. (e.g. `juju run {self.charm.app.name}/leader {PRECHECK_ACTION_NAME}`)"
            logger.debug(f"Pre-refresh check event failed: {message}")
            event.fail(message)
            return
        if not self._upgrade or self._upgrade.in_progress:
            message = "Refresh already in progress"
            logger.debug(f"Pre-refresh check failed: {message}")
            event.fail(message)
            return
        try:
            self._upgrade.pre_upgrade_check()
        except PrecheckFailed as exception:
            message = (
                f"Charm is not ready for refresh. Pre-refresh check failed: {exception.message}"
            )
            logger.debug(f"Pre-refresh check failed: {message}")
            event.fail(message)
            return
        message = "Charm is ready for refresh."
        event.set_results({"result": message})
        logger.debug(f"Pre-refresh check succeeded: {message}")

    def _on_resume_upgrade_action(self, event: ActionEvent) -> None:
        if not self.charm.unit.is_leader():
            message = f"Must run action on leader unit. (e.g. `juju run {self.charm.app.name}/leader {RESUME_ACTION_NAME}`)"
            logger.debug(f"Resume refresh event failed: {message}")
            event.fail(message)
            return
        if not self._upgrade or not self._upgrade.in_progress:
            message = "No refresh in progress"
            logger.debug(f"Resume refresh event failed: {message}")
            event.fail(message)
            return
        self._upgrade.reconcile_partition(action_event=event)

    def _on_force_upgrade_action(self, event: ActionEvent) -> None:
        if not self._upgrade or not self._upgrade.in_progress:
            message = "No refresh in progress"
            logger.debug(f"Force refresh failed: {message}")
            event.fail(message)
            return
        if not self._upgrade.upgrade_resumed:
            message = f"Run `juju run {self.charm.app.name}/leader {RESUME_ACTION_NAME}` before trying to force refresh"
            logger.debug(f"Force refresh event failed: {message}")
            event.fail(message)
            return
        if self._upgrade.unit_state != "outdated":
            message = "Unit already refreshed"
            logger.debug(f"Force refresh event failed: {message}")
            event.fail(message)
            return
        logger.debug("Forcing refresh")
        event.log(f"Forcefully refreshing {self.charm.unit.name}")
        self._upgrade.upgrade_unit(charm=self.charm)
        event.set_results({"result": f"Forcefully refreshed {self.charm.unit.name}"})
        logger.debug("Forced refresh")

    def run_post_app_upgrade_task(self, event: EventBase):
        """Runs the post upgrade check to verify that the cluster is healthy.

        By deferring before setting unit state to HEALTHY, the user will either:
            1. have to wait for the unit to resolve itself.
            2. have to run the force-upgrade action (to upgrade the next unit).
        """
        logger.debug("Running post refresh checks to verify cluster is not broken after refresh")
        self.run_post_upgrade_checks(event, finished_whole_cluster=False)

        if self._upgrade.unit_state != UnitState.HEALTHY:
            return

        logger.debug("Cluster is healthy after refreshing unit %s", self.charm.unit.name)

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
            logger.debug("Waiting to finalise refresh, one or more shards need refresh.")
            event.defer()
            return

        logger.debug(
            "Entire cluster has been refreshed, checking health of the cluster and enabling balancer."
        )
        self.run_post_upgrade_checks(event, finished_whole_cluster=True)

        try:
            with MongosConnection(self.charm.mongos_config) as mongos:
                mongos.start_and_wait_for_balancer()
        except BalancerNotEnabledError:
            logger.debug(
                "Need more time to enable the balancer after finishing the refresh. Deferring event."
            )
            event.defer()
            return

        self.set_mongos_feature_compatibilty_version(Config.Upgrade.FEATURE_VERSION_6)

    # END: Event handlers

    # BEGIN: Helpers
    def run_post_upgrade_checks(self, event, finished_whole_cluster: bool) -> None:
        """Runs post-upgrade checks for after a shard/config-server/replset/cluster upgrade."""
        upgrade_type = "unit." if not finished_whole_cluster else "sharded cluster"
        try:
            self.wait_for_cluster_healthy()
        except RetryError:
            logger.error(
                "Cluster is not healthy after refreshing %s. Will retry next juju event.",
                upgrade_type,
            )
            logger.info(ROLLBACK_INSTRUCTIONS)
            self.charm.status.set_and_share_status(Config.Status.UNHEALTHY_UPGRADE)
            event.defer()
            return

        if not self.is_cluster_able_to_read_write():
            logger.error(
                "Cluster is not healthy after refreshing %s, writes not propagated throughout cluster. Deferring post refresh check.",
                upgrade_type,
            )
            logger.info(ROLLBACK_INSTRUCTIONS)
            self.charm.status.set_and_share_status(Config.Status.UNHEALTHY_UPGRADE)
            event.defer()
            return

        if self.charm.unit.status == Config.Status.UNHEALTHY_UPGRADE:
            self.charm.status.set_and_share_status(ActiveStatus())

        self._upgrade.unit_state = UnitState.HEALTHY

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
                "Rollback with `juju refresh`. Pre-refresh check failed:"
            )
        ):
            self.charm.status.set_and_share_status(
                self._upgrade.get_unit_juju_status() or ActiveStatus()
            )

    # END: helpers
