# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In-place upgrades on machines.

Derived from specification: DA058 - In-Place Upgrades - Kubernetes v2
(https://docs.google.com/document/d/1tLjknwHudjcHs42nzPVBNkHs98XxAOT2BXGGpP7NyEU/)
"""
import json
import logging
import time
import typing

import ops

from config import Config
from upgrades import mongodb_upgrade, upgrade

logger = logging.getLogger(__name__)

_SNAP_REVISION = str(Config.SNAP_PACKAGES[0][2])


class Upgrade(upgrade.Upgrade):
    """In-place upgrades on machines."""

    @property
    def unit_state(self) -> typing.Optional[upgrade.UnitState]:
        """Returns the unit state."""
        if (
            self._unit_workload_container_version is not None
            and self._unit_workload_container_version != self._app_workload_container_version
        ):
            logger.debug("Unit upgrade state: outdated")
            return upgrade.UnitState.OUTDATED
        return super().unit_state

    @unit_state.setter
    def unit_state(self, value: upgrade.UnitState) -> None:
        # Super call
        upgrade.Upgrade.unit_state.fset(self, value)

    def _get_unit_healthy_status(self) -> ops.StatusBase:
        if self._unit_workload_container_version == self._app_workload_container_version:
            return ops.ActiveStatus(
                f'MongoDB {self._unit_workload_version} running; Snap rev {self._unit_workload_container_version}; Charmed operator {self._current_versions["charm"]}'
            )
        return ops.ActiveStatus(
            f'MongoDB {self._unit_workload_version} running; Snap rev {self._unit_workload_container_version} (outdated); Charmed operator {self._current_versions["charm"]}'
        )

    @property
    def app_status(self) -> typing.Optional[ops.StatusBase]:
        """App upgrade status."""
        if not self.is_compatible:
            logger.info(
                "Upgrade incompatible. If you accept potential *data loss* and *downtime*, you can continue by running `force-upgrade` action on each remaining unit"
            )
            return ops.BlockedStatus(
                "Upgrade incompatible. Rollback to previous revision with `juju refresh`"
            )
        return super().app_status

    @property
    def _unit_workload_container_versions(self) -> typing.Dict[str, str]:
        """{Unit name: installed snap revision}."""
        versions = {}
        for unit in self._sorted_units:
            if version := (self._peer_relation.data[unit].get("snap_revision")):
                versions[unit.name] = version
        return versions

    @property
    def _unit_workload_container_version(self) -> typing.Optional[str]:
        """Installed snap revision for this unit."""
        return self._unit_databag.get("snap_revision")

    @_unit_workload_container_version.setter
    def _unit_workload_container_version(self, value: str):
        self._unit_databag["snap_revision"] = value

    @property
    def _app_workload_container_version(self) -> str:
        """Snap revision for current charm code."""
        return _SNAP_REVISION

    @property
    def _unit_workload_version(self) -> typing.Optional[str]:
        """Installed OpenSearch version for this unit."""
        return self._unit_databag.get("workload_version")

    @_unit_workload_version.setter
    def _unit_workload_version(self, value: str):
        self._unit_databag["workload_version"] = value

    def reconcile_partition(self, *, action_event: ops.ActionEvent = None) -> None:
        """Handle Juju action to confirm first upgraded unit is healthy and resume upgrade."""
        if action_event:
            self.upgrade_resumed = True
            message = "Upgrade resumed."
            action_event.set_results({"result": message})
            logger.debug(f"Resume upgrade event succeeded: {message}")

    @property
    def upgrade_resumed(self) -> bool:
        """Whether user has resumed upgrade with Juju action.

        Reset to `False` after each `juju refresh`
        """
        return json.loads(self._app_databag.get("upgrade-resumed", "false"))

    @upgrade_resumed.setter
    def upgrade_resumed(self, value: bool):
        # Trigger peer relation_changed event even if value does not change
        # (Needed when leader sets value to False during `ops.UpgradeCharmEvent`)
        self._app_databag["-unused-timestamp-upgrade-resume-last-updated"] = str(time.time())

        self._app_databag["upgrade-resumed"] = json.dumps(value)
        logger.debug(f"Set upgrade-resumed to {value=}")

    @property
    def authorized(self) -> bool:
        """Whether this unit is authorized to upgrade.

        Only applies to machine charm.

        Raises:
            PrecheckFailed: App is not ready to upgrade
        """
        assert self._unit_workload_container_version != self._app_workload_container_version
        assert self.versions_set
        for index, unit in enumerate(self._sorted_units):
            # Higher number units have already upgraded
            if unit.name == self._unit.name:
                if index == 0:
                    if (
                        json.loads(self._app_databag["versions"])["charm"]
                        == self._current_versions["charm"]
                    ):
                        # Assumes charm version uniquely identifies charm revision
                        logger.debug("Rollback detected. Skipping pre-upgrade check")
                    else:
                        # Run pre-upgrade check
                        # (in case user forgot to run pre-upgrade-check action)
                        self.pre_upgrade_check()
                        logger.debug("Pre-upgrade check after `juju refresh` successful")
                elif index == 1:
                    # User confirmation needed to resume upgrade (i.e. upgrade second unit)
                    logger.debug(f"Second unit authorized to upgrade if {self.upgrade_resumed=}")
                    return self.upgrade_resumed
                return True
            state = self._peer_relation.data[unit].get("state")
            if state:
                state = upgrade.UnitState(state)
            if (
                self._unit_workload_container_versions.get(unit.name)
                != self._app_workload_container_version
                or state is not upgrade.UnitState.HEALTHY
            ):
                # Waiting for higher number units to upgrade
                return False
        return False

    def upgrade_unit(self, *, charm) -> None:
        """Runs the upgrade procedure.

        Only applies to machine charm.
        """
        # According to the MongoDB documentation, before upgrading the primary, we must ensure a
        # safe primary re-election.
        try:
            if self._unit.name == charm.primary:
                logger.debug("Stepping down current primary, before upgrading service...")
                charm.upgrade.step_down_primary_and_wait_reelection()
        except mongodb_upgrade.FailedToElectNewPrimaryError:
            # by not setting the snap revision and immediately returning, this function will be
            # called again, and an empty re-elect a primary will occur again.
            logger.error("Failed to reelect primary before upgrading unit.")
            return

        logger.debug(f"Upgrading {self.authorized=}")
        self.unit_state = upgrade.UnitState.UPGRADING
        charm.install_snap_packages(packages=Config.SNAP_PACKAGES)
        self._unit_databag["snap_revision"] = _SNAP_REVISION
        self._unit_workload_version = self._current_versions["workload"]
        logger.debug(f"Saved {_SNAP_REVISION} in unit databag after upgrade")

        # once the last unit has upgrade, notify relevant integrated applications of the new
        # version.
        if charm.unit == self._sorted_units[-1]:
            charm.version_checker.set_version_across_all_relations()

        # post upgrade check should be retried in case of failure, for this it is necessary to
        # emit a separate event.
        charm.upgrade.post_app_upgrade_event.emit()

    def save_snap_revision_after_first_install(self):
        """Set snap revision on first install."""
        self._unit_workload_container_version = _SNAP_REVISION
        self._unit_workload_version = self._current_versions["workload"]
        logger.debug(
            f'Saved {_SNAP_REVISION=} and {self._current_versions["workload"]=} in unit databag after first install'
        )
