# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class we manage client database relations.

This class creates user and database for each application relation
and expose needed information for client connection via fields in
external relation.
"""

import os
import logging
import pwd

from charms.operator_libs_linux.v1 import systemd
from charms.mongodb_libs.v0.helpers import KEY_FILE

from ops.framework import Object

from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus
)

# The unique Charmhub library identifier, never change it
LIBID = "1057f353503741a98ed79309b5be7e32"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version.
LIBPATCH = 0

logger = logging.getLogger(__name__)
REL_NAME = "obsolete"

# We expect the MongoDB container to use the default ports
MONGODB_PORT = 27017
MONGODB_VERSION = 5.0
PEER = "database-peers"
MONGO_USER = "mongodb"
MONGO_DATA_DIR = "/data/db"

class MongoDBLegacyProvider(Object):
    """In this class we manage client database relations."""

    def __init__(self, charm):
        """Manager of MongoDB client relations."""
        super().__init__(charm, "client-relations")
        self.charm = charm
        self.framework.observe(self.charm.on[REL_NAME].relation_created, self._on_relation_created)
        self.framework.observe(self.charm.on[REL_NAME].relation_joined, self._on_relation_joined)

    def _on_legacy_relation_created(self, event):
        """Legacy relations for MongoDB opporate without a password and so we update the server accordingly and 
        set a flag. 
        """
        logger.warning("DEPRECATION WARNING - `mongodb` interface is a legacy interface.")

        # TODO, future PR check if there are any new relations that are related to this charm and will be effected
        # by loss of password. If so go into blocked state. 


        # TODO set to no password mode 
        self._stop_mongod_service()
        self._update_mongod_service(auth=False)
        self._start_mongod_service()

    def _on_legacy_relation_joined(self, event):
        """
        NOTE: this is retro-fitted from the legacy mongodb charm: https://launchpad.net/charm-mongodb
        """
        logger.warning("DEPRECATION WARNING - `mongodb` interface is a legacy interface.")

        relation = self.model.get_relation(REL_NAME, event.relation.id)

        data = relation.data[self.charm.app]
        data["hostname"] = str(self.model.get_binding(PEER).network.bind_address)
        data["port"] = MONGODB_PORT
        data["type"] = "database"
        data["version"] = MONGODB_VERSION
        if self.model.get_relation(PEER).units > 0:
            data["replset"] = self.charm.app.name

        # reactive charms set relation data on "the current unit"
        relation.data[self.charm.unit].update(data)

    # TODO move to helpers 
    def _stop_mongod_service(self):
        self.unit.status = MaintenanceStatus("stopping MongoDB")
        if systemd.service_running("mongod.service"):
            logger.debug("stopping mongod.service")
            try:
                systemd.service_stop("mongod.service")
            except systemd.SystemdError:
                logger.error("failed to stop mongod.service")
                self.unit.status = BlockedStatus("couldn't start MongoDB")
                return

    # TODO move to helpers 
    def _update_mongod_service(self, auth:bool):
        mongod_start_args = self._generate_service_args(auth)

        with open("/lib/systemd/system/mongod.service", "r") as mongodb_service_file:
            mongodb_service = mongodb_service_file.readlines()

        # replace start command with our parameterized one
        for index, line in enumerate(mongodb_service):
            if "ExecStart" in line:
                mongodb_service[index] = mongod_start_args

        # systemd gives files in /etc/systemd/system/ precedence over those in /lib/systemd/system/
        # hence our changed file in /etc will be read while maintaining the original one in /lib.
        with open("/etc/systemd/system/mongod.service", "w") as service_file:
            service_file.writelines(mongodb_service)

        # mongod requires permissions to /data/db
        mongodb_user = pwd.getpwnam(MONGO_USER)
        os.chown(MONGO_DATA_DIR, mongodb_user.pw_uid, mongodb_user.pw_gid)

        # changes to service files are only applied after reloading
        systemd.daemon_reload()

    def _generate_service_args(self, auth:bool)-> str:
        # Construct the mongod startup commandline args for systemd, note that commandline
        # arguments take priority over any user set config file options. User options will be
        # configured in the config file. MongoDB handles this merge of these two options.
        machine_ip = self._unit_ip(self.unit)
        mongod_start_args = [
                "ExecStart=/usr/bin/mongod",
                # bind to localhost and external interfaces
                "--bind_ip",
                f"localhost,{machine_ip}",
                # part of replicaset
                "--replSet",
                f"{self.app.name}"
        ]

        if auth:
            mongod_start_args.append("--auth")
        
        mongod_start_args.extend([
                # keyFile used for authentication replica set peers
                # TODO: replace with x509
                "--clusterAuthMode=keyFile",
                f"--keyFile={KEY_FILE}",
                "\n",
                ]
            )

        mongod_start_args = " ".join(mongod_start_args)

        return mongod_start_args

    # TODO move to helpers 
    def _start_mongod_service(self):
        self.unit.status = MaintenanceStatus("starting MongoDB")
        if not systemd.service_running("mongod.service"):
            logger.debug("starting mongod.service")
            try:
                systemd.service_start("mongod.service")
            except systemd.SystemdError:
                logger.error("failed to enable mongod.service")
                self.unit.status = BlockedStatus("couldn't start MongoDB")
                return

            self.unit.status = ActiveStatus()


