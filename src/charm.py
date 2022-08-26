#!/usr/bin/env python3
"""Charm code for MongoDB service."""
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
import os
import pwd
import subprocess
from pathlib import Path
from subprocess import check_call
from typing import Dict, List, Optional
from urllib.request import URLError, urlopen

import ops.charm
from charms.mongodb_libs.v0.helpers import (
    KEY_FILE,
    generate_keyfile,
    generate_password,
    get_create_user_cmd,
)
from charms.mongodb_libs.v0.machine_helpers import (
    start_mongod_service,
    update_mongod_service,
)
from charms.mongodb_libs.v0.mongodb import (
    MongoDBConfiguration,
    MongoDBConnection,
    NotReadyError,
    PyMongoError,
)
from charms.mongodb_libs.v0.mongodb_provider import MongoDBProvider
from charms.mongodb_libs.v0.mongodb_vm_legacy_provider import MongoDBLegacyProvider
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    WaitingStatus,
)
from tenacity import before_log, retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

PEER = "database-peers"
REPO_URL = "deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"
REPO_ENTRY = (
    "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/5.0 multiverse"
)
GPG_URL = "https://www.mongodb.org/static/pgp/server-5.0.asc"
MONGO_EXEC_LINE = 10
MONGO_USER = "mongodb"
MONGO_DATA_DIR = "/data/db"

# We expect the MongoDB container to use the default ports
MONGODB_PORT = 27017

REL_NAME = "database"


class MongodbOperatorCharm(ops.charm.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self._port = MONGODB_PORT

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on[PEER].relation_joined, self._on_mongodb_relation_joined)
        self.framework.observe(self.on[PEER].relation_changed, self._on_mongodb_relation_handler)

        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.get_primary_action, self._on_get_primary_action)
        self.framework.observe(
            self.on.mongodb_storage_detaching, self._on_mongodb_storage_detaching
        )
        # if a new leader has been elected update hosts of MongoDB
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on[PEER].relation_departed, self._relation_departed)
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)

        # handle provider side of relations
        self.client_relations = MongoDBProvider(self, substrate="vm")
        self.legacy_client_relations = MongoDBLegacyProvider(self)

    def _generate_passwords(self) -> None:
        """Generate passwords and put them into peer relation.

        The same keyFile and admin password on all members needed, hence it is generated once and
        share between members via the app data.
        """
        if "admin_password" not in self.app_data:
            self.app_data["admin_password"] = generate_password()

        if "keyfile" not in self.app_data:
            self.app_data["keyfile"] = generate_keyfile()

    def _on_leader_elected(self, event) -> None:
        """Generates necessary keyfile and updates replica hosts."""
        if "keyfile" not in self.app_data:
            self._generate_passwords()

        self._update_hosts(event)

        try:
            self.update_app_relation_data()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _update_hosts(self, event) -> None:
        """Update replica set hosts and remove any unremoved replicas from the config."""
        if "db_initialised" not in self.app_data:
            return

        self.process_unremoved_units(event)
        self.app_data["replica_set_hosts"] = json.dumps(self._unit_ips)

    def _on_mongodb_storage_detaching(self, event: ops.charm.StorageDetachingEvent) -> None:
        """Before storage detaches, allow removing unit to remove itself from the set.

        If the removing unit is primary also allow it to step down and elect another unit as
        primary while it still has access to its storage.
        """
        try:
            # remove_replset_member retries for one minute in an attempt to resolve race conditions
            # it is not possible to defer in storage detached.
            with MongoDBConnection(self.mongodb_config) as mongo:
                logger.debug("Removing %s from replica set", self._unit_ip(self.unit))
                mongo.remove_replset_member(self._unit_ip(self.unit))
        except NotReadyError:
            logger.info(
                "Failed to remove %s from replica set, another member is syncing", self.unit.name
            )
        except PyMongoError as e:
            logger.error("Failed to remove %s from replica set, error=%r", self.unit.name, e)

    def update_app_relation_data(self) -> None:
        """Helper function to update application relation data."""
        if "db_initialised" not in self.app_data:
            return

        database_users = set()

        with MongoDBConnection(self.mongodb_config) as mongo:
            database_users = mongo.get_users()

        for relation in self.model.relations[REL_NAME]:
            username = self.client_relations._get_username_from_relation_id(relation.id)
            password = relation.data[self.app]["password"]
            config = self.client_relations._get_config(username, password)
            if username in database_users:
                data = relation.data[self.app]
                data["endpoints"] = ",".join(config.hosts)
                data["uris"] = config.uri
                relation.data[self.app].update(data)

    def _relation_departed(self, event: ops.charm.RelationDepartedEvent) -> None:
        """Remove peer from replica set if it wasn't able to remove itself.

        Args:
            event: The triggering relation departed event.
        """
        # allow leader to update relation data and hosts if it isn't leaving
        if not self.unit.is_leader() or event.departing_unit == self.unit:
            return
        self._update_hosts(event)

        try:
            self.update_app_relation_data()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def process_unremoved_units(self, event) -> None:
        """Removes replica set members that are no longer running as a juju hosts."""
        with MongoDBConnection(self.mongodb_config) as mongo:
            try:
                replset_members = mongo.get_replset_members()
                for member in replset_members - self.mongodb_config.hosts:
                    logger.debug("Removing %s from replica set", member)
                    mongo.remove_replset_member(member)
            except NotReadyError:
                logger.info("Deferring process_unremoved_units: another member is syncing")
                event.defer()
            except PyMongoError as e:
                logger.error("Deferring process_unremoved_units: error=%r", e)
                event.defer()

    def _on_mongodb_relation_joined(self, event: ops.charm.RelationJoinedEvent) -> None:
        """Add peer to replica set.

        Args:
            event: The triggering relation joined event.
        """
        if not self.unit.is_leader():
            return

        self._on_mongodb_relation_handler(event)
        try:
            self.update_app_relation_data()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _on_mongodb_relation_handler(self, event: ops.charm.RelationEvent) -> None:
        """Adds the unit as a replica to the MongoDB replica set.

        Args:
            event: The triggering relation joined/changed event.
        """
        # only leader should configure replica set and app-changed-events can trigger the relation
        # changed hook resulting in no JUJU_REMOTE_UNIT if this is the case we should return
        # further reconfiguration can be successful only if a replica set is initialised.

        if not (self.unit.is_leader() and event.unit) or "db_initialised" not in self.app_data:
            return

        with MongoDBConnection(self.mongodb_config) as mongo:
            try:
                replset_members = mongo.get_replset_members()
                # compare set of mongod replica set members and juju hosts to avoid the unnecessary
                # reconfiguration.
                if replset_members == self.mongodb_config.hosts:
                    return

                for member in self.mongodb_config.hosts - replset_members:
                    logger.debug("Adding %s to replica set", member)
                    with MongoDBConnection(
                        self.mongodb_config, member, direct=True
                    ) as direct_mongo:
                        if not direct_mongo.is_ready:
                            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
                            logger.debug("Deferring reconfigure: %s is not ready yet.", member)
                            event.defer()
                            return
                    mongo.add_replset_member(member)
            except NotReadyError:
                self.unit.status = WaitingStatus("waiting to reconfigure replica set")
                logger.error("Deferring reconfigure: another member doing sync right now")
                event.defer()
            except PyMongoError as e:
                self.unit.status = WaitingStatus("waiting to reconfigure replica set")
                logger.error("Deferring reconfigure: error=%r", e)
                event.defer()

    def _on_install(self, event) -> None:
        """Handle the install event (fired on startup).

        Handles the startup install event -- installs updates the apt cache,
        installs MongoDB.
        """
        self.unit.status = MaintenanceStatus("installing MongoDB")
        try:
            self._add_repository(REPO_URL, GPG_URL, REPO_ENTRY)
            self._install_apt_packages(["mongodb-org"])
        except (apt.InvalidSourceError, ValueError, apt.GPGKeyError, URLError):
            self.unit.status = BlockedStatus("couldn't install MongoDB")

        # if a new unit is joining a cluster with a legacy relation it should start without auth
        auth = not self.client_relations._get_users_from_relations(None, rel="obsolete")

        # Construct the mongod startup commandline args for systemd and reload the daemon.
        update_mongod_service(
            auth=auth, machine_ip=self._unit_ip(self.unit), replset=self.app.name
        )

    def _on_config_changed(self, _) -> None:
        """Event handler for configuration changed events."""
        # TODO
        # - update existing mongo configurations based on user preferences
        # - add additional configurations as according to spec doc
        pass

    def _on_start(self, event: ops.charm.StartEvent) -> None:
        """Enables MongoDB service and initialises replica set.

        Args:
            event: The triggering start event.
        """
        # MongoDB with authentication requires a keyfile
        self._instatiate_keyfile(event)

        try:
            logger.debug("starting MongoDB.")
            self.unit.status = MaintenanceStatus("starting MongoDB")
            start_mongod_service()
            self.unit.status = ActiveStatus()
        except systemd.SystemdError:
            self.unit.status = BlockedStatus("couldn't start MongoDB")
            return

        try:
            self._open_port_tcp(self._port)
        except subprocess.CalledProcessError:
            self.unit.status = BlockedStatus("failed to open TCP port for MongoDB")
            return

        # check if this unit's deployment of MongoDB is ready
        with MongoDBConnection(self.mongodb_config, "localhost", direct=True) as direct_mongo:
            if not direct_mongo.is_ready:
                logger.debug("mongodb service is not ready yet.")
                self.unit.status = WaitingStatus("waiting for MongoDB to start")
                event.defer()
                return

        # mongod is now active
        self.unit.status = ActiveStatus()

        # only leader should initialise the replica set
        if not self.unit.is_leader():
            return

        self._initialise_replica_set(event)

    def _on_update_status(self, _):
        # cannot have both legacy and new relations since they have different auth requirements
        if self.client_relations._get_users_from_relations(
            None, rel="obsolete"
        ) and self.client_relations._get_users_from_relations(None):
            self.unit.status = BlockedStatus("cannot have both legacy and new relations")
            return

        # if unit is primary then update status
        if self._primary == self.unit.name:
            self.unit.status = ActiveStatus("Replica set primary")
        else:
            self.unit.status = ActiveStatus()

    def _on_get_primary_action(self, event: ops.charm.ActionEvent):
        event.set_results({"replica-set-primary": self._primary})

    def _on_get_admin_password(self, event: ops.charm.ActionEvent) -> None:
        """Returns the password for the user as an action response."""
        event.set_results({"admin-password": self.app_data.get("admin_password")})

    def _open_port_tcp(self, port: int) -> None:
        """Open the given port.

        Args:
            port: The port to open.
        """
        try:
            logger.debug("opening tcp port")
            check_call(["open-port", "{}/TCP".format(port)])
        except subprocess.CalledProcessError as e:
            logger.exception("failed opening port: %s", str(e))
            raise

    def _add_repository(
        self, repo_url: str, gpg_url: str, repo_entry: str
    ) -> apt.RepositoryMapping:
        """Adds MongoDB repo to container.

        Args:
            repo_url: deb-https url of repo to add
            gpg_url: url to retrieve GPP key
            repo_entry: a string representing a repository entry
        """
        repositories = apt.RepositoryMapping()

        # Add the repository if it doesn't already exist
        if repo_url not in repositories:
            # Get GPG key
            try:
                key = urlopen(gpg_url).read().decode()
            except URLError as e:
                logger.exception("failed to get GPG key, reason: %s", e)
                self.unit.status = BlockedStatus("couldn't install MongoDB")
                return

            # Add repository
            try:
                repo = apt.DebianRepository.from_repo_line(repo_entry)
                # Import the repository's key
                repo.import_key(key)
                repositories.add(repo)
            except (apt.InvalidSourceError, ValueError, apt.GPGKeyError) as e:
                logger.error("failed to add repository: %s", str(e))
                raise e

        return repositories

    def _install_apt_packages(self, packages: List[str]) -> None:
        """Installs package(s) to container.

        Args:
            packages: list of packages to install.
        """
        try:
            logger.debug("updating apt cache")
            apt.update()
        except subprocess.CalledProcessError as e:
            logger.exception("failed to update apt cache: %s", str(e))
            self.unit.status = BlockedStatus("couldn't install MongoDB")
            return

        try:
            logger.debug("installing apt packages: %s", ", ".join(packages))
            apt.add_package(packages)
        except apt.PackageNotFoundError:
            logger.error("a specified package not found in package cache or on system")
            self.unit.status = BlockedStatus("couldn't install MongoDB")
        except TypeError as e:
            logger.error("could not add package(s) to install: %s", str(e))
            self.unit.status = BlockedStatus("couldn't install MongoDB")

    def _instatiate_keyfile(self, event: ops.charm.StartEvent) -> None:
        # wait for keyFile to be created by leader unit
        if "keyfile" not in self.app_data:
            logger.debug("waiting for leader unit to generate keyfile contents")
            event.defer()
            return

        # put keyfile on the machine with appropriate permissions
        Path("/etc/mongodb/").mkdir(parents=True, exist_ok=True)
        with open(KEY_FILE, "w") as key_file:
            key_file.write(self.app_data.get("keyfile"))

        os.chmod(KEY_FILE, 0o400)
        mongodb_user = pwd.getpwnam(MONGO_USER)
        os.chown(KEY_FILE, mongodb_user.pw_uid, mongodb_user.pw_gid)

    def _initialise_replica_set(self, event: ops.charm.StartEvent) -> None:
        if "db_initialised" in self.app_data:
            # The replica set should be initialised only once. Check should be
            # external (e.g., check initialisation inside peer relation). We
            # shouldn't rely on MongoDB response because the data directory
            # can be corrupted.
            return

        with MongoDBConnection(self.mongodb_config, "localhost", direct=True) as direct_mongo:
            try:
                logger.info("Replica Set initialization")
                direct_mongo.init_replset()
                self._peers.data[self.app]["replica_set_hosts"] = json.dumps(
                    [self._unit_ip(self.unit)]
                )
                logger.info("User initialization")
                self._init_admin_user()
                logger.info("Manage relations")
                self.client_relations.oversee_users(None, None)
            except subprocess.CalledProcessError as e:
                logger.error(
                    "Deferring on_start: exit code: %i, stderr: %s", e.exit_code, e.stderr
                )
                event.defer()
                self.unit.status = WaitingStatus("waiting to initialise replica set")
                return
            except PyMongoError as e:
                logger.error("Deferring on_start since: error=%r", e)
                event.defer()
                self.unit.status = WaitingStatus("waiting to initialise replica set")
                return

            # replica set initialised properly and ready to go
            self.app_data["db_initialised"] = "True"
            self.unit.status = ActiveStatus()

    def _unit_ip(self, unit: ops.model.Unit) -> str:
        """Returns the ip address of a given unit."""
        # check if host is current host
        if unit == self.unit:
            return str(self.model.get_binding(PEER).network.bind_address)
        # check if host is a peer
        elif unit in self._peers.data:
            return str(self._peers.data[unit].get("private-address"))
        # raise exception if host not found
        else:
            raise ApplicationHostNotFoundError

    @property
    def _primary(self) -> str:
        """Retrieves the unit with the primary replica."""
        try:
            with MongoDBConnection(self.mongodb_config) as mongo:
                primary_ip = mongo.primary()
        except PyMongoError as e:
            logger.error("Unable to access primary due to: %s", e)
            return None

        # check if current unit matches primary ip
        if primary_ip == self._unit_ip(self.unit):
            return self.unit.name

        # check if peer unit matches primary ip
        for unit in self._peers.units:
            if primary_ip == self._unit_ip(unit):
                return unit.name

        return None

    @property
    def _unit_ips(self) -> List[str]:
        """Retrieve IP addresses associated with MongoDB application.

        Returns:
            a list of IP address associated with MongoDB application.
        """
        peer_addresses = [self._unit_ip(unit) for unit in self._peers.units]

        logger.debug("peer addresses: %s", peer_addresses)
        self_address = self._unit_ip(self.unit)
        logger.debug("unit address: %s", self_address)
        addresses = []
        if peer_addresses:
            addresses.extend(peer_addresses)
        addresses.append(self_address)
        return addresses

    @property
    def _replica_set_hosts(self):
        """Fetch current list of hosts in the replica set.

        Returns:
            A list of hosts addresses (strings).
        """
        return json.loads(self.app_data.get("replica_set_hosts", "[]"))

    @property
    def mongodb_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for this deployment of MongoDB."""
        return MongoDBConfiguration(
            replset=self.app.name,
            database="admin",
            username="operator",
            password=self.app_data.get("admin_password"),
            hosts=set(self._unit_ips),
            roles={"default"},
        )

    @property
    def app_data(self) -> Dict:
        """Peer relation data object."""
        relation = self.model.get_relation(PEER)
        if not relation:
            return {}

        return relation.data[self.app]

    @property
    def _peers(self) -> Optional[Relation]:
        """Fetch the peer relation.

        Returns:
             An `ops.model.Relation` object representing the peer relation.
        """
        return self.model.get_relation(PEER)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _init_admin_user(self) -> None:
        """Creates initial admin user for MongoDB.

        Initial admin user can be created only through localhost connection.
        see https://www.mongodb.com/docs/manual/core/localhost-exception/
        unfortunately, pymongo unable to create connection that considered
        as local connection by MongoDB, even if socket connection used.
        As a result, where are only hackish ways to create initial user.
        It is needed to install mongodb-clients inside charm container to make
        this function work correctly.
        """
        if "user_created" in self.app_data or not self.unit.is_leader():
            return

        out = subprocess.run(
            get_create_user_cmd(self.mongodb_config),
            input=self.mongodb_config.password.encode(),
        )
        if out.returncode == 0:
            raise AdminUserCreationError

        logger.debug("User created")
        self.app_data["user_created"] = "True"


class AdminUserCreationError(Exception):
    """Raised when a commands to create an admin user on MongoDB fail."""

    pass


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""

    pass


if __name__ == "__main__":
    main(MongodbOperatorCharm)
