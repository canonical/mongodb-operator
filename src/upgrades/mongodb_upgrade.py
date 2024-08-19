# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling MongoDB in-place upgrades."""

import logging
from typing import Optional

from charms.mongodb.v0.upgrade_helpers import (
    ROLLBACK_INSTRUCTIONS,
    GenericMongoDBUpgrade,
)
from charms.mongodb.v1.mongos import BalancerNotEnabledError, MongosConnection
from ops.charm import ActionEvent, CharmBase
from ops.framework import EventBase
from ops.model import ActiveStatus, BlockedStatus
from tenacity import RetryError

from config import Config
from upgrades import machine_upgrade, upgrade

logger = logging.getLogger(__name__)


class MongoDBUpgrade(GenericMongoDBUpgrade):
    """Handlers for upgrade events."""

    def __init__(self, charm: CharmBase):
        self.charm = charm
        super().__init__(charm, upgrade.PEER_RELATION_ENDPOINT_NAME)

    def _observe_events(self, charm: CharmBase) -> None:
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

    # BEGIN: properties
    @property
    def _upgrade(self) -> Optional[machine_upgrade.Upgrade]:
        try:
            return machine_upgrade.Upgrade(self.charm)
        except upgrade.PeerRelationNotReady:
            pass

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

    # END: helpers
