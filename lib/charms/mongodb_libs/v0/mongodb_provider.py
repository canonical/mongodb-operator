# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class we manage client database relations.

This class creates user and database for each application relation
and expose needed information for client connection via fields in
external relation.
"""
import ops.model
import os
import pwd
import re
import logging
from typing import Optional, Set

import json
from collections import namedtuple
from ops.charm import RelationChangedEvent

from charms.mongodb_libs.v0.helpers import generate_password
from charms.mongodb_libs.v0.mongodb import (
    MongoDBConfiguration,
    MongoDBConnection,
)
from ops.framework import Object
from ops.model import Relation, ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.charm import RelationBrokenEvent
from pymongo.errors import PyMongoError

from charms.operator_libs_linux.v1 import systemd
from charms.mongodb_libs.v0.helpers import KEY_FILE


# The unique Charmhub library identifier, never change it
LIBID = "1057f353503741a98ed79309b5be7e32"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version.
LIBPATCH = 0

logger = logging.getLogger(__name__)
REL_NAME = "database"

LEGACY_REL_NAME = "obsolete"

# We expect the MongoDB container to use the default ports
MONGODB_PORT = 27017
MONGODB_VERSION = "5.0"
PEER = "database-peers"
MONGO_USER = "mongodb"
MONGO_DATA_DIR = "/data/db"

Diff = namedtuple("Diff", "added changed deleted")
Diff.__doc__ = """
A tuple for storing the diff between two data mappings.
added - keys that were added
changed - keys that still exist but have new values
deleted - key that were deleted"""


class MongoDBProvider(Object):
    """In this class we manage client database relations."""

    def __init__(self, charm):
        """Manager of MongoDB client relations."""
        super().__init__(charm, "client-relations")
        self.charm = charm
        self.framework.observe(self.charm.on[REL_NAME].relation_joined, self._on_relation_event)
        self.framework.observe(self.charm.on[REL_NAME].relation_changed, self._on_relation_event)
        self.framework.observe(self.charm.on[REL_NAME].relation_broken, self._on_relation_event)
        self.framework.observe(
            self.charm.on[LEGACY_REL_NAME].relation_created, self._on_legacy_relation_created
        )
        self.framework.observe(
            self.charm.on[LEGACY_REL_NAME].relation_joined, self._on_legacy_relation_joined
        )

    ################################################################################
    # NEW RELATIONS
    ################################################################################
    def _on_relation_event(self, event):
        """Handle relation joined events.

        When relations join, change, or depart, the :class:`MongoDBClientRelation`
        creates or drops MongoDB users and sets credentials into relation
        data. As result, related charm gets credentials for accessing the
        MongoDB database.
        """
        logger.debug("Relation event thinks relation event is %s", event.relation.id)
        if not self.charm.unit.is_leader():
            return
        # We shouldn't try to create or update users if the database is not
        # initialised. We will create users as part of initialisation.
        if "db_initialised" not in self.charm.app_data:
            return

        departed_relation_id = None
        if type(event) is RelationBrokenEvent:
            departed_relation_id = event.relation.id

        try:
            self.oversee_users(departed_relation_id, event)
        except PyMongoError as e:
            logger.error("Deferring _on_relation_event since: error=%r", e)
            event.defer()
            return

    def oversee_users(self, departed_relation_id: Optional[int], event):
        """Oversees the users of the application.

        Function manages user relations by removing, updated, and creating
        users; and dropping databases when necessary.

        Args:
            departed_relation_id: When specified execution of functions
                makes sure to exclude the users and databases and remove
                them if necessary.

        When the function is executed in relation departed event, the departed
        relation is still in the list of all relations. Therefore, for proper
        work of the function, we need to exclude departed relation from the list.
        """
        with MongoDBConnection(self.charm.mongodb_config) as mongo:
            database_users = mongo.get_users()
            relation_users = self._get_users_from_relations(departed_relation_id)

            for username in database_users - relation_users:
                logger.info("Remove relation user: %s", username)
                mongo.drop_user(username)

            for username in relation_users - database_users:
                config = self._get_config(username)
                if config.database is None:
                    # We need to wait for moment when provider library
                    # set the database name into the relation.
                    continue
                logger.info("Create relation user: %s on %s", config.username, config.database)
                mongo.create_user(config)
                self._set_relation(config)

            for username in relation_users.intersection(database_users):
                config = self._get_config(username)
                logger.info("Update relation user: %s on %s", config.username, config.database)
                mongo.update_user(config)
                logger.info("Updating relation data according to diff")
                self._diff(event)

            if not self.charm.model.config["auto-delete"]:
                return

            database_dbs = mongo.get_databases()
            relation_dbs = self._get_databases_from_relations(departed_relation_id)
            for database in database_dbs - relation_dbs:
                logger.info("Drop database: %s", database)
                mongo.drop_database(database)

    ################################################################################
    # LEGACY RELATIONS
    ################################################################################
    def _on_legacy_relation_created(self, event):
        """Legacy relations for MongoDB opporate without a password and so we update the server accordingly and
        set a flag.
        """
        logger.warning("DEPRECATION WARNING - `mongodb` interface is a legacy interface.")

        # TODO, future PR check if there are any new relations that are related to this charm and will be effected
        # by loss of password. If so go into blocked state.

        # TODO, future PR check if already running without auth
        self._stop_mongod_service()
        self._update_mongod_service(auth=False)
        self._start_mongod_service()

    def _on_legacy_relation_joined(self, event):
        """
        NOTE: this is retro-fitted from the legacy mongodb charm: https://launchpad.net/charm-mongodb
        """
        logger.warning("DEPRECATION WARNING - `mongodb` interface is a legacy interface.")
        if not self.charm.unit.is_leader:
            return

        relation = self.model.get_relation(REL_NAME, event.relation.id)

        # reactive charms set relation data on "the current unit"
        data = relation.data[self.charm.unit]
        data["hostname"] = str(self.model.get_binding(PEER).network.bind_address)
        data["port"] = str(MONGODB_PORT)
        data["type"] = "database"
        data["version"] = MONGODB_VERSION
        data["replset"] = self.charm.app.name

        # reactive charms set relation data on "the current unit"
        relation.data[self.charm.unit].update(data)

    # TODO move to machine charm helpers
    def _stop_mongod_service(self):
        self.charm.unit.status = MaintenanceStatus("stopping MongoDB")
        if systemd.service_running("mongod.service"):
            logger.debug("stopping mongod.service")
            try:
                systemd.service_stop("mongod.service")
            except systemd.SystemdError:
                logger.error("failed to stop mongod.service")
                self.charm.unit.status = BlockedStatus("couldn't start MongoDB")
                return

    # TODO move to machine charm helpers
    def _update_mongod_service(self, auth: bool):
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

    # TODO move to machine charm helpers
    def _generate_service_args(self, auth: bool) -> str:
        # Construct the mongod startup commandline args for systemd, note that commandline
        # arguments take priority over any user set config file options. User options will be
        # configured in the config file. MongoDB handles this merge of these two options.
        machine_ip = self._unit_ip(self.charm.unit)
        mongod_start_args = [
            "ExecStart=/usr/bin/mongod",
            # bind to localhost and external interfaces
            "--bind_ip",
            f"localhost,{machine_ip}",
            # part of replicaset
            "--replSet",
            f"{self.charm.app.name}",
        ]

        if auth:
            mongod_start_args.extend(
                [
                    "--auth",
                    # keyFile used for authenti cation replica set peers, cluster auth, implies user authentication hence we cannot have cluster authentication without user authentication. see: https://www.mongodb.com/docs/manual/reference/configuration-options/#mongodb-setting-security.keyFile
                    # TODO: replace with x509
                    "--clusterAuthMode=keyFile",
                    f"--keyFile={KEY_FILE}",
                ]
            )

        mongod_start_args.append("\n")
        mongod_start_args = " ".join(mongod_start_args)

        return mongod_start_args

    # TODO move to machine charm helpers
    def _start_mongod_service(self):
        self.charm.unit.status = MaintenanceStatus("starting MongoDB")
        if not systemd.service_running("mongod.service"):
            logger.debug("starting mongod.service")
            try:
                systemd.service_start("mongod.service")
            except systemd.SystemdError:
                logger.error("failed to enable mongod.service")
                self.charm.unit.status = BlockedStatus("couldn't start MongoDB")
                return

            self.charm.unit.status = ActiveStatus()

    # TODO move to machine charm helpers
    def _unit_ip(self, unit: ops.model.Unit) -> str:
        """Returns the ip address of a given unit."""
        # check if host is current host
        if unit == self.charm.unit:
            return str(self.model.get_binding(PEER).network.bind_address)
        # check if host is a peer
        elif unit in self._peers.data:
            return str(self._peers.data[unit].get("private-address"))
        # raise exception if host not found
        else:
            raise ApplicationHostNotFoundError

    ################################################################################
    # HELPERS
    ################################################################################
    def _diff(self, event: RelationChangedEvent) -> Diff:
        """Retrieves the diff of the data in the relation changed databag.
        Args:
            event: relation changed event.
        Returns:
            a Diff instance containing the added, deleted and changed
                keys from the event relation databag.
        """
        # TODO import marcelos unit tests in a future PR
        # Retrieve the old data from the data key in the application relation databag.
        old_data = json.loads(event.relation.data[self.charm.model.app].get("data", "{}"))
        # Retrieve the new data from the event relation databag.
        new_data = {
            key: value for key, value in event.relation.data[event.app].items() if key != "data"
        }

        # These are the keys that were added to the databag and triggered this event.
        added = new_data.keys() - old_data.keys()
        # These are the keys that were removed from the databag and triggered this event.
        deleted = old_data.keys() - new_data.keys()
        # These are the keys that already existed in the databag,
        # but had their values changed.
        changed = {
            key for key in old_data.keys() & new_data.keys() if old_data[key] != new_data[key]
        }

        # TODO: update when evaluatation of the possibility of losing the diff is completed
        # happens in the charm before the diff is completely checked (DPE-412).
        # Convert the new_data to a serializable format and save it for a next diff check.
        event.relation.data[self.charm.model.app].update({"data": json.dumps(new_data)})

        # Return the diff with all possible changes.
        return Diff(added, changed, deleted)

    def _get_config(self, username: str) -> MongoDBConfiguration:
        """Construct config object for future user creation."""
        relation = self._get_relation_from_username(username)
        return MongoDBConfiguration(
            replset=self.charm.app.name,
            database=self._get_database_from_relation(relation),
            username=username,
            password=generate_password(),
            hosts=self.charm.mongodb_config.hosts,
            roles=self._get_roles_from_relation(relation),
        )

    def _set_relation(self, config: MongoDBConfiguration):
        """Save all output fields into application relation."""
        relation = self._get_relation_from_username(config.username)
        if relation is None:
            return None

        data = relation.data[self.charm.app]
        data["username"] = config.username
        data["password"] = config.password
        data["database"] = config.database
        data["endpoints"] = ",".join(config.hosts)
        data["replset"] = config.replset
        data["uris"] = config.uri
        relation.data[self.charm.app].update(data)

    @staticmethod
    def _get_username_from_relation_id(relation_id: str) -> str:
        """Construct username."""
        return f"relation-{relation_id}"

    def _get_users_from_relations(self, departed_relation_id: Optional[int]):
        """Return usernames for all relations except departed relation."""
        relations = self.model.relations[REL_NAME]
        return set(
            [
                self._get_username_from_relation_id(relation.id)
                for relation in relations
                if relation.id != departed_relation_id
            ]
        )

    def _get_databases_from_relations(self, departed_relation_id: Optional[int]) -> Set[str]:
        """Return database names from all relations.

        Args:
            departed_relation_id: when specified return all database names
                except for those databases that belong to the departing
                relation specified.
        """
        relations = self.model.relations[REL_NAME]
        databases = set()
        for relation in relations:
            if relation.id == departed_relation_id:
                continue
            database = self._get_database_from_relation(relation)
            if database is not None:
                databases.add(database)
        return databases

    def _get_relation_from_username(self, username: str) -> Relation:
        """Parse relation ID from a username and return Relation object."""
        match = re.match(r"^relation-(\d+)$", username)
        # We generated username in `_get_users_from_relations`
        # func and passed it into this function later.
        # It means the username here MUST match to regex.
        assert match is not None, "No relation match"
        relation_id = int(match.group(1))
        logger.debug("Relation ID: %s", relation_id)
        return self.model.get_relation(REL_NAME, relation_id)

    def _get_database_from_relation(self, relation: Relation) -> Optional[str]:
        """Return database name from relation."""
        database = relation.data[relation.app].get("database", None)
        if database is not None:
            return database
        return None

    def _get_roles_from_relation(self, relation: Relation) -> Set[str]:
        """Return additional user roles from relation if specified or return None."""
        roles = relation.data[relation.app].get("extra-user-roles", None)
        if roles is not None:
            return set(roles.split(","))
        return {"default"}


# TODO move this somewhere appropriate
class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""

    pass
