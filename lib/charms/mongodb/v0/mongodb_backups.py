# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage backup configurations and actions.

Specifically backups are handled with Percona Backup MongoDB (pbm) which is installed as a snap
during the install phase. A user for PBM is created when MongoDB is first started during the
start phase. This user is named "backup".
"""
import logging
import subprocess

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


PBM_S3_CONFIGS = [
    ("storage.s3.region", "s3-storage-region"),
    ("storage.s3.bucket", "s3-storage-bucket"),
    ("storage.s3.prefix", "s3-storage-prefix"),
    ("storage.s3.credentials.access-key-id", "s3-access-key-id"),
    ("storage.s3.credentials.secret-access-key", "s3-secret-access-key"),
    ("storage.s3.serverSideEncryption.kmsKeyID", "s3-kms-key-id"),
]


class MongoDBBackups(Object):
    """In this class, we manage mongodb backups."""

    def __init__(self, charm, substrate="k8s"):
        """Manager of MongoDB client relations."""
        super().__init__(charm, "client-relations")
        self.charm = charm
        self.substrate = substrate
        self.framework.observe(self.charm.on.config_changed, self._on_pbm_config_changed)

    def _on_pbm_config_changed(self, event) -> None:
        """Handles PBM configurations."""
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

        # parse user configurations
        for (snap_config_name, charm_config_name) in PBM_S3_CONFIGS:
            if self.charm.config.get(charm_config_name):
                pbm_configs[snap_config_name] = self.charm.config.get(charm_config_name)

        for (pbm_key, pbm_value) in pbm_configs.items():
            try:
                self._pbm_set_config(pbm_key, pbm_value)
            except subprocess.CalledProcessError as e:
                logger.error(
                    "Failed to configure the PBM snap with key=value %s=%s, failed with error: %s",
                    str(pbm_key),
                    str(pbm_value),
                    str(e),
                )
                self.charm.unit.status = BlockedStatus("couldn't configure s3 backup options.")
                return

        self.charm.unit.status = ActiveStatus("")

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
