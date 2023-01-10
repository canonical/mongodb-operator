# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage client database relations.

This class creates a user and database for each application relation
and expose needed information for client connection via fields in
external relation.
"""
from charms.operator_libs_linux.v1 import snap
from charms.mongodb.v0.mongodb import MongoDBConfiguration, MongoDBConnection
from charms.mongodb.v0.helpers import generate_password
import logging
from collections import namedtuple

from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus
from pymongo.errors import PyMongoError, OperationFailure

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

PBM_PRIVILEGES = {"resource": {"anyResource": True}, "actions": ["anyAction"]}


class MongoDBBackups(Object):
    """In this class, we manage client database relations."""

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

        try:
            self.create_pbm_user()
        except PyMongoError as e:
            self.charm.unit.status = BlockedStatus("config change failed")
            logger.error("Deferring config_changed since: error=%r", e)
            event.defer()
            return

        # presets for PBM snap configurations
        pbm_configs = {}
        pbm_configs["uri"] = self._pbm_config.uri
        pbm_configs["storage.s3.type"] = "s3"
        pbm_configs["storage.s3.serverSideEncryption.sseAlgorithm"] = "aws:kms"

        # parse user configurations
        for (snap_config_name, charm_config_name) in PBM_S3_CONFIGS:
            if self.charm.config.get(charm_config_name):
                pbm_configs[snap_config_name] = self.charm.config.get(charm_config_name)

        try:
            pbm_snap.set(pbm_configs)
            self.charm.unit.status = ActiveStatus("")
        except snap.SnapError as e:
            logger.error(
                "Failed to configure the PBM snap with the configurations: %s, failed with error: %s",
                str(pbm_configs),
                str(e),
            )
            self.charm.unit.status = BlockedStatus("couldn't configure s3 backup options.")

    def create_pbm_user(self):
        """Creates the PBM user on the MongoDB database."""
        with MongoDBConnection(self.charm.mongodb_config) as mongo:
            # first we must create the necessary roles for PBM
            logger.debug("creating the PBM user roles...")
            mongo.create_role(role_name="pbmAnyAction", privileges=PBM_PRIVILEGES)
            logger.debug("creating the PBM user...")
            try:
                mongo.create_user(self._pbm_config)
            except OperationFailure as e:
                if not e.code == 51003:  # User already exists
                    logger.error("Cannot add user. error=%r", e)
                    raise

    @property
    def _pbm_config(self) -> MongoDBConfiguration:
        """Construct the config object for pbm user and creates user if necessary."""
        if not self.charm.get_secret("app", "pbm_password"):
            self.charm.set_secret("app", "pbm_password", generate_password())

        return MongoDBConfiguration(
            replset=self.charm.app.name,
            database="admin",
            username="pbmuser",
            password=self.charm.get_secret("app", "pbm_password"),
            hosts=self.charm.mongodb_config.hosts,
            roles=["pbm"],
            tls_external=self.charm.tls.get_tls_files("unit") is not None,
            tls_internal=self.charm.tls.get_tls_files("unit") is not None,
        )
