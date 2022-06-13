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
from charms.mongodb_libs.v0.mongodb import MongoDBConfiguration, MongoDBConnection
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

from mongod_helpers import (
    MONGODB_PORT,
    ConfigurationError,
    ConnectionFailure,
    MongoDB,
    NotReadyError,
    OperationFailure,
    PyMongoError,
)

logger = logging.getLogger(__name__)

PEER = "mongodb"
REPO_URL = "deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"
REPO_ENTRY = (
    "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/5.0 multiverse"
)
GPG_URL = "https://www.mongodb.org/static/pgp/server-5.0.asc"
MONGO_EXEC_LINE = 10
MONGO_USER = "mongodb"
MONGO_DATA_DIR = "/data/db"


class MongodbOperatorCharm(ops.charm.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self._port = MONGODB_PORT

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.mongodb_relation_joined, self._on_mongodb_relation_handler)
        self.framework.observe(self.on.mongodb_relation_changed, self._on_mongodb_relation_handler)

        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.get_primary_action, self._on_get_primary_action)
        self.framework.observe(
            self.on.mongodb_storage_detaching, self._on_mongodb_storage_detaching
        )
        # if a new leader has been elected update hosts of MongoDB
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.mongodb_relation_departed, self._relation_departed)
        self.framework.observe(self.on.get_admin_password_action, self._on_get_admin_password)

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

    def _update_hosts(self, event) -> None:
        """Update replica set hosts and remove any unremoved replicas from the config."""
        if "replset_initialised" not in self.app_data:
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
            logger.info("Failed to remove %s from replica set, error=%r", self.unit.name, e)

    def _relation_departed(self, event: ops.charm.RelationDepartedEvent) -> None:
        """Remove peer from replica set if it wasn't able to remove itself.

        Args:
            event: The triggering relation departed event.
        """
        # allow leader to update hosts if it isn't leaving
        if self.unit.is_leader() and not event.departing_unit == self.unit:
            self._update_hosts(event)

    def process_unremoved_units(self, event) -> None:
        """Removes replica set members that are no longer running as a juju hosts."""
        with MongoDBConnection(self.mongodb_config) as mongo:
            try:
                replset_members = mongo.get_replset_members
                for member in replset_members - self.mongodb_config.hosts:
                    logger.debug("Removing %s from replica set", member)
                    mongo.remove_replset_member(member)
            except NotReadyError:
                logger.info("Deferring process_unremoved_units: another member is syncing")
                event.defer()
            except PyMongoError as e:
                logger.info("Deferring process_unremoved_units: error=%r", e)
                event.defer()

    def _on_mongodb_relation_handler(self, event: ops.charm.RelationEvent) -> None:
        """Adds the unit as a replica to the MongoDB replica set.

        Args:
            event: The triggering relation joined/changed event.
        """
        # only leader should configure replica set and app-changed-events can trigger the relation
        # changed hook resulting in no JUJU_REMOTE_UNIT if this is the case we should return
        if not (self.unit.is_leader() and event.unit):
            return

        #  only add the calling unit to the replica set if it has mongod running
        calling_unit = event.unit
        calling_unit_ip = str(self._peers.data[calling_unit].get("private-address"))
        logger.debug("Adding %s to replica set", calling_unit_ip)
        with MongoDBConnection(self.mongodb_config, calling_unit_ip, direct=True) as direct_mongo:
            if not direct_mongo.is_ready:
                logger.debug("Deferring reconfigure: %s is not ready yet.", calling_unit_ip)
                event.defer()
                return

        # TODO in a future PR update this use of self._mongo to be with MongoDBConnection
        # only reconfigure if all current replicas of MongoDB application are in ready state
        if not self._mongo.all_replicas_ready():
            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
            logger.debug("waiting for all replica set hosts to be ready")
            event.defer()
            return

        logger.debug("unit: %s is ready to join the replica set", calling_unit.name)
        self._add_replica(event)

    def _add_replica(self, event: ops.charm.RelationEvent) -> None:
        """Adds RelationEvent triggering unit to the replica set.

        Args:
            event: The triggering relation event.
        """
        # check if reconfiguration is necessary
        if not self._need_replica_set_reconfiguration:
            self.unit.status = ActiveStatus()
            return

        try:
            # TODO in a future PR update this use of self._mongo to be with MongoDBConnection
            self._mongo.reconfigure_replica_set()
            # update the set of replica set hosts
            self.app_data["replica_set_hosts"] = json.dumps(self._unit_ips)
            logger.debug("Replica set successfully reconfigured")
            self.unit.status = ActiveStatus()
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            logger.error("deferring reconfigure of replica set: %s", str(e))
            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
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

        # Construct the mongod startup commandline args for systemd, note that commandline
        # arguments take priority over any user set config file options. User options will be
        # configured in the config file. MongoDB handles this merge of these two options.
        machine_ip = self._unit_ip(self.unit)
        mongod_start_args = " ".join(
            [
                "ExecStart=/usr/bin/mongod",
                # bind to localhost and external interfaces
                "--bind_ip",
                f"localhost,{machine_ip}",
                # part of replicaset
                "--replSet",
                "rs0",
                "--auth",
                # keyFile used for authentication replica set peers
                # TODO: replace with x509
                "--clusterAuthMode=keyFile",
                f"--keyFile={KEY_FILE}",
                "\n",
            ]
        )

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

        # start mongo service
        self.unit.status = MaintenanceStatus("starting MongoDB")
        if not systemd.service_running("mongod.service"):
            logger.debug("starting mongod.service")
            try:
                systemd.service_start("mongod.service")
            except systemd.SystemdError:
                logger.error("failed to enable mongod.service")
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
        # if unit is primary then update status
        if self._primary == self.unit.name:
            self.unit.status = ActiveStatus("Replica set primary")

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
            self.unit.status = WaitingStatus("waiting for MongoDB to start")
            event.defer()
            return

        # TODO in follow up PR add error handling for keyfile creation & permissions
        # put keyfile on the machine with appropriate permissions
        Path("/etc/mongodb/").mkdir(parents=True, exist_ok=True)
        with open(KEY_FILE, "w") as key_file:
            key_file.write(self.app_data.get("keyfile"))

        os.chmod(KEY_FILE, 0o400)
        mongodb_user = pwd.getpwnam(MONGO_USER)
        os.chown(KEY_FILE, mongodb_user.pw_uid, mongodb_user.pw_gid)

    def _initialise_replica_set(self, event: ops.charm.StartEvent) -> None:
        with MongoDBConnection(self.mongodb_config, "localhost", direct=True) as direct_mongo:
            try:
                logger.info("Replica Set initialization")
                direct_mongo.init_replset()
                self._peers.data[self.app]["replica_set_hosts"] = json.dumps(
                    [self._unit_ip(self.unit)]
                )
                logger.info("User initialization")
                self._init_admin_user()
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
            self.app_data["replset_initialised"] = "True"
            self.unit.status = ActiveStatus()

    def _single_mongo_replica(self, ip_address: str) -> MongoDB:
        """Fetch the MongoDB server interface object for a single replica.

        Args:
            ip_address: ip_address for the replica of interest.

        Returns:
            A MongoDB server object.
        """
        unit_config = self._config
        unit_config["calling_unit_ip"] = ip_address
        return MongoDB(unit_config)

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
    def _need_replica_set_reconfiguration(self) -> bool:
        """Does MongoDB replica set need reconfiguration.

        Returns:
            bool: that indicates if the replica set hosts should be reconfigured
        """
        # are the units for the application all assigned to a host
        return set(self._unit_ips) != set(self._replica_set_hosts)

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
    def _config(self) -> dict:
        """Retrieve config options for MongoDB.

        Returns:
            A dictionary representation of MongoDB config options.
        """
        # TODO parameterize remaining config options
        config = {
            "app_name": self.app.name,
            "replica_set_name": "rs0",
            "num_hosts": len(self._unit_ips),
            "port": self._port,
            "root_password": self.app_data.get("admin_password"),
            "security_key": "",
            "unit_ips": self._unit_ips,
            "replica_set_hosts": self._replica_set_hosts,
            "calling_unit_ip": self._unit_ip(self.unit),
            "username": "operator",
        }
        return config

    # TODO remove one of the mongodb configs.
    # there are two mongodb configs, because we are currently in the process of slowly phasing out
    # the src/mongod_helpers.py file with the lib/charms/mongodb_libs/v0/mongodb.py. When the
    # src/mongod_helpers.py file is fully phased out the property _config will be removed and only
    # mongodb_config will be present
    @property
    def mongodb_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for this deployment of MongoDB."""
        return MongoDBConfiguration(
            replset="rs0",  # TODO update this to self.app.name
            database="admin",
            username="operator",
            password=self.app_data.get("admin_password"),
            hosts=set(self._unit_ips),
            roles={"default"},
        )

    @property
    def _mongo(self) -> MongoDB:
        """Fetch the MongoDB server interface object.

        Returns:
            A MongoDB server object.
        """
        return MongoDB(self._config)

    @property
    def app_data(self) -> Dict:
        """Peer relation data object."""
        return self.model.get_relation(PEER).data[self.app]

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
        out = subprocess.run(
            get_create_user_cmd(self.mongodb_config),
            input=self.mongodb_config.password.encode(),
        )
        if out.returncode == 0:
            raise AdminUserCreationError
        logger.debug("User created")


class AdminUserCreationError(Exception):
    """Raised when a commands to create an admin user on MongoDB fail."""

    pass


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""

    pass


if __name__ == "__main__":
    main(MongodbOperatorCharm)
