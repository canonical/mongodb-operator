# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling MongoDB in-place upgrades."""

import logging
from typing import Optional

from upgrades import machine_upgrade
from upgrades import upgrade
from ops.charm import ActionEvent, CharmBase
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

from config import Config

logger = logging.getLogger(__name__)


WRITE_KEY = "write_value"
UPGRADE_RELATION = "upgrade"


class MongoDBUpgrade(Object):
    """Handlers for upgrade events."""

    def __init__(self, charm: CharmBase):
        self.charm = charm
        super().__init__(charm, UPGRADE_RELATION)
        self.framework.observe(
            charm.on[Config.Upgrade.RELATION_NAME].relation_created,
            self._on_upgrade_peer_relation_created,
        )
        self.framework.observe(
            charm.on[Config.Upgrade.RELATION_NAME].relation_changed, self._reconcile_upgrade
        )
        self.framework.observe(charm.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(
            charm.on[upgrade.RESUME_ACTION_NAME].action, self._on_resume_upgrade_action
        )
        self.framework.observe(charm.on["force-upgrade"].action, self._on_force_upgrade_action)

    # BEGIN: Event handlers
    def _on_upgrade_peer_relation_created(self, _) -> None:
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

                # TODO - check if we need to pass any arguments, also pass the snap
                self._upgrade.upgrade_unit()
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
            message = f"Must run action on leader unit. (e.g. `juju run {self.app.name}/leader {upgrade.RESUME_ACTION_NAME}`)"
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
            message = f"Run `juju run {self.app.name}/leader resume-upgrade` before trying to force upgrade"
            logger.debug(f"Force upgrade event failed: {message}")
            event.fail(message)
            return
        if self._upgrade.unit_state != "outdated":
            message = "Unit already upgraded"
            logger.debug(f"Force upgrade event failed: {message}")
            event.fail(message)
            return
        logger.debug("Forcing upgrade")
        event.log(f"Forcefully upgrading {self.unit.name}")
        self._upgrade_opensearch_event.emit(ignore_lock=event.params["ignore-lock"])
        event.set_results({"result": f"Forcefully upgraded {self.unit.name}"})
        logger.debug("Forced upgrade")

    # END: Event handlers

    # BEGIN: Helpers
    def _set_upgrade_status(self):
        # Set/clear upgrade unit status if no other unit status
        if isinstance(self.charm.unit.status, ActiveStatus) or (
            isinstance(self.charm.unit.status, WaitingStatus)
            and self.charm.unit.status.message.startswith("Charmed operator upgraded.")
        ):
            self.charm.unit.status = self._upgrade.get_unit_juju_status() or ActiveStatus()
        if not self.charm.unit.is_leader():
            return
        # Set upgrade app status
        if status := self._upgrade.app_status:
            self.charm.app.status = status
        else:
            # Clear upgrade app status
            if (
                isinstance(self.charm.app.status, BlockedStatus)
                or isinstance(self.charm.app.status, MaintenanceStatus)
            ) and self.charm.app.status.message.startswith("Upgrad"):
                self.charm.app.status = ActiveStatus()

    # END: helpers

    # BEGIN: properties
    @property
    def _upgrade(self) -> Optional[machine_upgrade.Upgrade]:
        try:
            return machine_upgrade.Upgrade(self.charm)
        except upgrade.PeerRelationNotReadyError:
            pass
