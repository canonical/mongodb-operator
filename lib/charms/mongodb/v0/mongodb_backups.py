# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage backup configurations and actions.

Specifically backups are handled with Percona Backup MongoDB (pbm) which is installed as a snap
during the install phase. A user for PBM is created when MongoDB is first started during the
start phase. This user is named "backup".
"""
import json
import logging
import re
import subprocess
import time
from typing import Dict

from charms.data_platform_libs.v0.s3 import CredentialsChangedEvent, S3Requirer
from charms.mongodb.v0.helpers import generate_password
from charms.mongodb.v0.mongodb import MongoDBConfiguration
from charms.operator_libs_linux.v1 import snap
from ops.framework import Object
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    StatusBase,
    WaitingStatus,
)
from tenacity import (
    Retrying,
    before_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

# The unique Charmhub library identifier, never change it
LIBID = "18c461132b824ace91af0d7abe85f40e"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

logger = logging.getLogger(__name__)

S3_PBM_OPTION_MAP = {
    "region": "storage.s3.region",
    "bucket": "storage.s3.bucket",
    "path": "storage.s3.prefix",
    "access-key": "storage.s3.credentials.access-key-id",
    "secret-key": "storage.s3.credentials.secret-access-key",
    "endpoint": "storage.s3.endpointUrl",
    "storage-class": "storage.s3.storageClass",
}
S3_RELATION = "s3-credentials"
REMAPPING_PATTERN = r"\ABackup doesn't match current cluster topology - it has different replica set names. Extra shards in the backup will cause this, for a simple example. The extra/unknown replica set names found in the backup are: ([^,\s]+)([.] Backup has no data for the config server or sole replicaset)?\Z"


class ResyncError(Exception):
    """Raised when pbm is resyncing configurations and is not ready to be used."""


class SetPBMConfigError(Exception):
    """Raised when pbm cannot configure a given option."""


class PBMBusyError(Exception):
    """Raised when PBM is busy and cannot run another operation."""


class MongoDBBackups(Object):
    """In this class, we manage mongodb backups."""

    def __init__(self, charm, substrate="k8s"):
        """Manager of MongoDB client relations."""
        super().__init__(charm, "client-relations")
        self.charm = charm
        self.substrate = substrate

        # s3 relation handles the config options for s3 backups
        self.s3_client = S3Requirer(self.charm, S3_RELATION)
        self.framework.observe(
            self.s3_client.on.credentials_changed, self._on_s3_credential_changed
        )
        self.framework.observe(self.charm.on.create_backup_action, self._on_create_backup_action)
        self.framework.observe(self.charm.on.list_backups_action, self._on_list_backups_action)
        self.framework.observe(self.charm.on.restore_action, self._on_restore_action)

    def _on_s3_credential_changed(self, event: CredentialsChangedEvent):
        """Sets pbm credentials, resyncs if necessary and reports config errors."""
        # handling PBM configurations requires that MongoDB is running and the pbm snap is
        # installed.
        if "db_initialised" not in self.charm.app_peer_data:
            logger.debug("Cannot set PBM configurations, MongoDB has not yet started.")
            event.defer()
            return

        snap_cache = snap.SnapCache()
        pbm_snap = snap_cache["percona-backup-mongodb"]
        if not pbm_snap.present:
            logger.debug("Cannot set PBM configurations, PBM snap is not yet installed.")
            event.defer()
            return

        # pbm requires that the URI is set before adding configs
        pbm_snap.set({"uri": self._backup_config.uri})

        # Add and sync configuration options while handling errors related to configuring options
        # and re-syncing PBM.
        try:
            self._set_config_options(self._get_pbm_configs())
            self._resync_config_options(pbm_snap)
        except SetPBMConfigError:
            self.charm.unit.status = BlockedStatus("couldn't configure s3 backup options.")
            return
        except snap.SnapError as e:
            logger.error("An exception occurred when starting pbm agent, error: %s.", str(e))
            self.charm.unit.status = BlockedStatus("couldn't start pbm")
            return
        except ResyncError:
            self.charm.unit.status = WaitingStatus("waiting to sync s3 configurations.")
            event.defer()
            logger.debug("Sync-ing configurations needs more time.")
            return
        except PBMBusyError:
            self.charm.unit.status = WaitingStatus("waiting to sync s3 configurations.")
            logger.debug(
                "Cannot update configs while PBM is running, must wait for PBM action to finish."
            )
            event.defer()
            return
        except subprocess.CalledProcessError as e:
            logger.error("Syncing configurations failed: %s", str(e))

        self.charm.unit.status = self._get_pbm_status()

    def _get_pbm_configs(self) -> Dict:
        """Returns a dictionary of desired PBM configurations."""
        pbm_configs = {"storage.type": "s3"}
        credentials = self.s3_client.get_s3_connection_info()
        for s3_option, s3_value in credentials.items():
            if s3_option not in S3_PBM_OPTION_MAP:
                continue

            pbm_configs[S3_PBM_OPTION_MAP[s3_option]] = s3_value
        return pbm_configs

    def _set_config_options(self, pbm_configs):
        """Applying given configurations with pbm."""
        # the pbm tool can only set one configuration at a time.
        for pbm_key, pbm_value in pbm_configs.items():
            try:
                self._pbm_set_config(pbm_key, pbm_value)
            except subprocess.CalledProcessError:
                # do not log the error since the error outputs the command that was run. The
                # command can include credentials that should not be logged.
                logger.error(
                    "Failed to configure the PBM snap option: %s",
                    pbm_key,
                )
                raise SetPBMConfigError

    def _resync_config_options(self, pbm_snap):
        """Attempts to sync pbm config options and sets status in case of failure."""
        pbm_snap.start(services=["pbm-agent"])

        # pbm has a flakely resync and it is necessary to wait for no actions to be running before
        # resync-ing. See: https://jira.percona.com/browse/PBM-1038
        for attempt in Retrying(
            stop=stop_after_attempt(20),
            wait=wait_fixed(5),
            reraise=True,
        ):
            with attempt:
                pbm_status = self._get_pbm_status()
                if isinstance(pbm_status, MaintenanceStatus) or isinstance(
                    pbm_status, WaitingStatus
                ):
                    raise PBMBusyError

        # wait for re-sync and update charm status based on pbm syncing status. Need to wait for
        # 2 seconds for pbm_agent to receive the resync command before verifying.
        subprocess.check_output("percona-backup-mongodb config --force-resync", shell=True)
        time.sleep(2)
        self._wait_pbm_status()

    def _get_pbm_status(self) -> StatusBase:
        """Retrieve pbm status."""
        snap_cache = snap.SnapCache()
        pbm_snap = snap_cache["percona-backup-mongodb"]
        if not pbm_snap.present:
            return BlockedStatus("pbm not installed.")

        try:
            pbm_status = subprocess.check_output(
                "percona-backup-mongodb status", shell=True, stderr=subprocess.STDOUT
            )
            # pbm is running resync operation
            if "Resync" in self._current_pbm_op(pbm_status.decode("utf-8")):
                return WaitingStatus("waiting to sync s3 configurations.")

            # no operations are currently running with pbm
            if "(none)" in self._current_pbm_op(pbm_status.decode("utf-8")):
                return ActiveStatus("")

            if "Snapshot backup" in self._current_pbm_op(pbm_status.decode("utf-8")):
                return MaintenanceStatus("backup started/running")

            if "Snapshot restore" in self._current_pbm_op(pbm_status.decode("utf-8")):
                return MaintenanceStatus("restore started/running")

        except subprocess.CalledProcessError as e:
            # pbm pipes a return code of 1, but its output shows the true error code so it is
            # necessary to parse the output
            error_message = e.output.decode("utf-8")
            if "status code: 403" in error_message:
                return BlockedStatus("s3 credentials are incorrect.")

            return BlockedStatus("s3 configurations are incompatible.")
        return ActiveStatus("")

    @retry(
        stop=stop_after_attempt(20),
        reraise=True,
        retry=retry_if_exception_type(ResyncError),
        before=before_log(logger, logging.DEBUG),
    )
    def _wait_pbm_status(self) -> None:
        """Wait for pbm_agent to resolve errors and return the status of pbm.

        The pbm status is set by the pbm_agent daemon which needs time to both resync and resolve
        errors in configurations. Resync-ing is a longer process and should take around 5 minutes.
        Configuration errors generally occur when the configurations change and pbm_agent is
        updating, this is generally quick and should take <15s. If errors are not resolved in 15s
        it means there is an incorrect configuration which will require user intervention.

        Retrying for resync is handled by decorator, retrying for configuration errors is handled
        within this function.
        """
        # on occasion it takes the pbm_agent daemon time to update its configs, meaning that it
        # will error for incorrect configurations for <15s before resolving itself.
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_fixed(5),
            reraise=True,
        ):
            with attempt:
                pbm_status = subprocess.check_output("percona-backup-mongodb status", shell=True)
                if "Resync" in self._current_pbm_op(pbm_status.decode("utf-8")):
                    # since this process takes several minutes we should let the user know
                    # immediately.
                    self.charm.unit.status = WaitingStatus("waiting to sync s3 configurations.")
                    raise ResyncError

    def _current_pbm_op(self, pbm_status: str) -> str:
        """Parses pbm status for the operation that pbm is running."""
        pbm_status = pbm_status.splitlines()
        for i in range(0, len(pbm_status)):
            line = pbm_status[i]

            # operation is two lines after the line "Currently running:"
            if line == "Currently running:":
                return pbm_status[i + 2]

        return ""

    def _pbm_set_config(self, key: str, value: str) -> None:
        """Runs the percona-backup-mongodb config command for the provided key and value."""
        config_cmd = f'percona-backup-mongodb config --set {key}="{value}"'
        subprocess.check_output(config_cmd, shell=True)

    def _on_create_backup_action(self, event) -> None:
        if self.model.get_relation(S3_RELATION) is None:
            event.fail("Relation with s3-integrator charm missing, cannot create backup.")
            return

        # only leader can create backups. This prevents multiple backups from being attempted at
        # once.
        if not self.charm.unit.is_leader():
            event.fail("The action can be run only on leader unit.")
            return

        # cannot create backup if pbm is not ready. This could be due to: resyncing, incompatible,
        # options, incorrect credentials, or already creating a backup
        pbm_status = self._get_pbm_status()
        self.charm.unit.status = pbm_status
        if isinstance(pbm_status, MaintenanceStatus):
            event.fail(
                "Can only create one backup at a time, please wait for current backup to finish."
            )
            return
        if isinstance(pbm_status, WaitingStatus):
            event.defer()
            logger.debug(
                "Sync-ing configurations needs more time, must wait before creating a backup."
            )
            return
        if isinstance(pbm_status, BlockedStatus):
            event.fail(f"Cannot create backup {pbm_status.message}.")
            return

        try:
            subprocess.check_output("percona-backup-mongodb backup", shell=True)
            event.set_results({"backup-status": "backup started"})
            self.charm.unit.status = MaintenanceStatus("backup started/running")
        except subprocess.CalledProcessError as e:
            event.fail(f"Failed to backup MongoDB with error: {str(e)}")
            return

    def _on_list_backups_action(self, event) -> None:
        if self.model.get_relation(S3_RELATION) is None:
            event.fail("Relation with s3-integrator charm missing, cannot list backups.")
            return

        # cannot list backups if pbm is resyncing, or has incompatible options or incorrect
        # credentials
        pbm_status = self._get_pbm_status()
        self.charm.unit.status = pbm_status
        if isinstance(pbm_status, WaitingStatus):
            event.defer()
            logger.debug(
                "Sync-ing configurations needs more time, must wait before listing backups."
            )
            return
        if isinstance(pbm_status, BlockedStatus):
            event.fail(f"Cannot list backups: {pbm_status.message}.")
            return

        try:
            formatted_list = self._generate_backup_list_output()
            event.set_results({"backups": formatted_list})
        except subprocess.CalledProcessError as e:
            event.fail(f"Failed to list MongoDB backups with error: {str(e)}")
            return

    def _on_restore_action(self, event) -> None:
        if self.model.get_relation(S3_RELATION) is None:
            event.fail("Relation with s3-integrator charm missing, cannot restore from a backup.")
            return

        backup_id = event.params.get("backup-id")
        if not backup_id:
            event.fail("Missing backup-id to restore")
            return

        # cannot restore backup if pbm is not ready. This could be due to: resyncing, incompatible,
        # options, incorrect credentials, creating a backup, or already performing a restore.
        pbm_status = self._get_pbm_status()
        self.charm.unit.status = pbm_status
        if isinstance(pbm_status, MaintenanceStatus):
            event.fail("Please wait for current backup/restore to finish.")
            return
        if isinstance(pbm_status, WaitingStatus):
            event.defer()
            logger.debug("Sync-ing configurations needs more time, must wait before restoring.")
            return
        if isinstance(pbm_status, BlockedStatus):
            event.fail(f"Cannot create backup {pbm_status.message}.")
            return

        try:
            remapping_args = self._remap_replicaset(backup_id)
            subprocess.check_output(
                f"percona-backup-mongodb restore {backup_id} {remapping_args}",
                shell=True,
                stderr=subprocess.STDOUT,
            )
            event.set_results({"restore-status": "restore started"})
            self.charm.unit.status = MaintenanceStatus("restore started/running")
        except subprocess.CalledProcessError as e:
            error_message = e.output.decode("utf-8")
            if f"backup '{backup_id}' not found" in error_message:
                event.fail(
                    f"Backup id: {backup_id} does not exist in list of backups, please check list-backups for the available backup_ids."
                )
                return

            event.fail(f"Failed to restore MongoDB with error: {str(e)}")
            return

    def _backup_from_different_cluster(self, backup_status: str) -> bool:
        """Returns if a given backup was made on a different cluster."""
        return re.search(REMAPPING_PATTERN, backup_status) is not None

    def _remap_replicaset(self, backup_id: str) -> str:
        """Returns options for remapping a replica set during a cluster migration restore.

        Args:
            backup_id: str of the backup to check for remapping

        Raises: CalledProcessError
        """
        pbm_status = subprocess.check_output(
            "percona-backup-mongodb status --out=json", shell=True, stderr=subprocess.STDOUT
        )
        pbm_status = json.loads(pbm_status.decode("utf-8"))

        # grab the error status from the backup if present
        backups = pbm_status["backups"]["snapshot"] or []
        backup_status = ""
        for backup in backups:
            if not backup_id == backup["name"]:
                continue

            backup_status = backup.get("error", "")
            break

        if not self._backup_from_different_cluster(backup_status):
            return ""

        # TODO in the future when we support conf servers and shards this will need to be more
        # comprehensive.
        old_cluster_name = re.search(REMAPPING_PATTERN, backup_status).group(1)
        current_cluster_name = self.charm.app.name
        logger.debug(
            "Replica set remapping is necessary for restore, old cluster name: %s ; new cluster name: %s",
            old_cluster_name,
            current_cluster_name,
        )
        return f"--replset-remapping {current_cluster_name}={old_cluster_name}"

    def _generate_backup_list_output(self) -> str:
        """Generates a list of backups in a formatted table.

        List contains successful, failed, and in progress backups in order of ascending time.

        Raises CalledProcessError
        """
        backup_list = []
        pbm_status = subprocess.check_output(
            "percona-backup-mongodb status --out=json", shell=True, stderr=subprocess.STDOUT
        )
        # processes finished and failed backups
        pbm_status = json.loads(pbm_status.decode("utf-8"))
        backups = pbm_status["backups"]["snapshot"] or []
        for backup in backups:
            backup_status = "finished"
            if backup["status"] == "error":
                backup_status = "failed"
            if backup["status"] != "error" and backup["status"] != "done":
                backup_status = "in progress"
            backup_list.append((backup["name"], backup["type"], backup_status))

        # process in progress backups
        running_backup = pbm_status["running"]
        if running_backup.get("type", None) == "backup":
            # backups are sorted in reverse order
            last_reported_backup = backup_list[0]
            # pbm will occasionally report backups that are currently running as failed, so it is
            # necessary to correct the backup list in this case.
            if last_reported_backup[0] == running_backup["name"]:
                backup_list[0] = (last_reported_backup[0], last_reported_backup[1], "in progress")
            else:
                backup_list.append((running_backup["name"], "logical", "in progress"))

        # sort by time and return formatted output
        return self._format_backup_list(sorted(backup_list, key=lambda pair: pair[0]))

    def _format_backup_list(self, backup_list) -> str:
        """Formats provided list of backups as a table."""
        backups = ["{:<21s} | {:<12s} | {:s}".format("backup-id", "backup-type", "backup-status")]

        backups.append("-" * len(backups[0]))
        for backup_id, backup_type, backup_status in backup_list:
            backups.append(
                "{:<21s} | {:<12s} | {:s}".format(backup_id, backup_type, backup_status)
            )

        return "\n".join(backups)

    @property
    def _backup_config(self) -> MongoDBConfiguration:
        """Construct the config object for backup user and creates user if necessary."""
        if not self.charm.get_secret("app", "backup_password"):
            self.charm.set_secret("app", "backup_password", generate_password())

        return MongoDBConfiguration(
            replset=self.charm.app.name,
            database="",
            username="backup",
            password=self.charm.get_secret("app", "backup_password"),
            hosts=[
                self.charm._unit_ip(self.charm.unit)
            ],  # pbm cannot make a direct connection if multiple hosts are used
            roles=["backup"],
            tls_external=self.charm.tls.get_tls_files("unit") is not None,
            tls_internal=self.charm.tls.get_tls_files("app") is not None,
        )
