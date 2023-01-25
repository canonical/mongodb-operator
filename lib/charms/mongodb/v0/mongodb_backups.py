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
from ops.model import ActiveStatus, BlockedStatus

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
}
S3_RELATION = "s3-credentials"


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

        # URI is set with `snap set`
        pbm_snap.set({"uri": self._backup_config.uri})

        # presets for PBM snap configurations
        pbm_configs = {}
        pbm_configs["storage.type"] = "s3"
        pbm_configs["storage.s3.serverSideEncryption.sseAlgorithm"] = "aws:kms"

        credentials = self.s3_client.get_s3_connection_info()
        for s3_option, s3_value in credentials.items():
            if s3_option not in S3_PBM_OPTION_MAP:
                continue

            pbm_name = S3_PBM_OPTION_MAP[s3_option]
            pbm_configs[pbm_name] = s3_value

        for (pbm_key, pbm_value) in pbm_configs.items():
            try:
                self._pbm_set_config(pbm_key, pbm_value)
            except subprocess.CalledProcessError as e:
                logger.error(
                    "Failed to configure the PBM snap failed with error: %s",
                    str(e),
                )
                self.charm.unit.status = BlockedStatus("couldn't configure s3 backup options.")
                return

        self.charm.unit.status = ActiveStatus("")

        logger.info(f"First relation updated credentials: {credentials}")

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
