# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage backup configurations and actions.

Specifically backups are handled with Percona Backup MongoDB (pbm) which is installed as a snap
during the install phase. A user for PBM is created when MongoDB is first started during the
start phase. This user is named "backup".
"""
import logging
import subprocess

from charms.data_platform_libs.v0.s3 import CredentialsChangedEvent, S3Requirer
from charms.mongodb.v0.helpers import generate_password
from charms.mongodb.v0.mongodb import MongoDBConfiguration
from charms.operator_libs_linux.v1 import snap
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from tenacity import (
    Retrying,
    before_log,
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception_type,
)

# The unique Charmhub library identifier, never change it
LIBID = "18c461132b824ace91af0d7abe85f40e"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

CREDENTIALS_CODE = 403

logger = logging.getLogger(__name__)

S3_PBM_OPTION_MAP = {
    "region": "storage.s3.region",
    "bucket": "storage.s3.bucket",
    "path": "storage.s3.prefix",
    "access-key": "storage.s3.credentials.access-key-id",
    "secret-key": "storage.s3.credentials.secret-access-key",
}
S3_RELATION = "s3-credentials"


class ResyncError(Exception):
    "Raised when pbm is resyncing configurations and is not ready to be used."


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

    def _on_s3_credential_changed(self, event: CredentialsChangedEvent):
        """Sets pbm credentials, resyncs if necessary and reports config errors."""
        # handling PBM configurations requires that the pbm snap is installed.
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

        # URI is set with `snap set` -- pbm requires that the URI is set before adding configs
        pbm_snap.set({"uri": self._backup_config.uri})

        # presets for PBM snap configurations
        pbm_configs = {}
        pbm_configs["storage.type"] = "s3"

        credentials = self.s3_client.get_s3_connection_info()
        for s3_option, s3_value in credentials.items():
            if s3_option not in S3_PBM_OPTION_MAP:
                continue

            pbm_configs[S3_PBM_OPTION_MAP[s3_option]] = s3_value

        # the pbm tool can only set one configuration at a time.
        for (pbm_key, pbm_value) in pbm_configs.items():
            try:
                self._pbm_set_config(pbm_key, pbm_value)
            except subprocess.CalledProcessError:
                # do not log the error since the error outputs the command that was run. The
                # command can include credentials that should not be logged.
                logger.error(
                    "Failed to configure the PBM snap option: %s",
                    pbm_key,
                )
                self.charm.unit.status = BlockedStatus("couldn't configure s3 backup options.")
                return

        try:
            pbm_snap.start(services=["pbm-agent"])
        except snap.SnapError as e:
            logger.error("An exception occurred when starting pbm agent, error: %s.", str(e))
            self.charm.unit.status = BlockedStatus("couldn't start pbm")
            return

        subprocess.check_output("percona-backup-mongodb config --force-resync", shell=True)

        # wait for re-sync and check if pbm is ready.
        status = self._get_pbm_status()
        self.charm.unit.status = status
        if isinstance(status, WaitingStatus):
            event.defer()
            return

    def _get_pbm_status(self):
        """Returns pbm status based on whether pbm can accept new configurations.

        The status of pbm is determined by whether or not pbm_agent is able to accept its given
        configs. Depending on whether or not pbm was able to resolve and resync config changes
        pbm_agent will be ready/not ready for backups.
        """
        try:
            # get pbm status waits for resync up to 5 minutes
            self._resolve_pbm()
        except ResyncError:
            return WaitingStatus("waiting to sync s3 configurations.")
        except subprocess.CalledProcessError as e:
            if e.returncode == CREDENTIALS_CODE:  # 403
                logger.error(e)
                return BlockedStatus("s3 credentials are incorrect.")

            logger.error(e)
            return BlockedStatus("s3 configurations are incompatible.")

        return ActiveStatus("")

    @retry(
        stop=stop_after_attempt(20),
        reraise=True,
        retry=retry_if_exception_type(ResyncError),
        before=before_log(logger, logging.DEBUG),
    )
    def _resolve_pbm(self) -> None:
        """Wait for pbm_agent to resolve errors and return the status of pbm.

        The pbm status is set by the pbm_agent daemon which needs time to both resync and resolve
        errors in configurations. Resync-ing is a longer process and should take around 5 minutes.
        Configuration errors generally occur when the configurations change and pbm_agent is
        updating, this is generally quick and should take <15s. If errors are not resolved in 30s
        it means there is an incorrect configuration which will require user intervention.

        Retrying for resync is handled by decorator, retrying for configuration errors is handled
        within this function.
        """
        # on occassion it takes the pbm_agent daemon time to update its configs, meaning that it
        # will error for incorrect configurations for <15s before resolving itself.
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_fixed(5),
            reraise=True,
        ):
            with attempt:
                pbm_status = subprocess.check_output("percona-backup-mongodb status", shell=True)
                if "Resync" in self._current_pbm_op(pbm_status.decode("utf-8")):
                    # since this process takes several minutes we should let the user know immediately.
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

    @property
    def _backup_config(self) -> MongoDBConfiguration:
        """Construct the config object for backup user and creates user if necessary."""
        if not self.charm.get_secret("app", "backup_password"):
            self.charm.set_secret("app", "backup_password", generate_password())

        return MongoDBConfiguration(
            replset=self.charm.app.name,
            database="admin",
            username="backup",
            password=self.charm.get_secret("app", "backup_password"),
            hosts=self.charm.mongodb_config.hosts,
            roles=["backup"],
            tls_external=self.charm.tls.get_tls_files("unit") is not None,
            tls_internal=self.charm.tls.get_tls_files("app") is not None,
        )
