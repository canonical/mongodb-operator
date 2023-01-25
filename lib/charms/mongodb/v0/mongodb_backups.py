# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage backup configurations and actions.

Specifically backups are handled with Percona Backup MongoDB (pbm) which is installed as a snap
during the install phase. A user for PBM is created when MongoDB is first started during the
start phase. This user is named "backup".
"""
import logging
import subprocess
import time

from charms.mongodb.v0.helpers import generate_password
from charms.mongodb.v0.mongodb import MongoDBConfiguration
from charms.operator_libs_linux.v1 import snap
from ops.framework import Object

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
        self.framework.observe(self.charm.on.create_backup_action, self._on_create_backup_action)

    def _on_create_backup_action(self, event) -> None:
        try:
            snap_cache = snap.SnapCache()
            pbm_snap = snap_cache["percona-backup-mongodb"]
            if not pbm_snap.present:
                logger.debug("Cannot start PBM agent, PBM snap is not yet installed.")
                event.defer()
                return
            pbm_snap.start(services=["pbm-agent"])
            # sleep for 10 seconds while pbm snap service starts. Without this running backup will
            # occasionally fail.
            time.sleep(10)
        except snap.SnapError as e:
            logger.error("An exception occurred when starting pbm agent, error: %s.", str(e))
            event.fail(f"Failed to backup MongoDB with error: {str(e)}")
            return

        try:
            subprocess.check_output("percona-backup-mongodb backup", shell=True)
            event.set_results({"backup-status": "backup started"})
        except subprocess.CalledProcessError as e:
            event.fail(f"Failed to backup MongoDB with error: {str(e)}")
            return

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
