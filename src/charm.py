#!/usr/bin/env python3
"""Charm code for MongoDB service."""
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
import subprocess
from subprocess import check_call
from typing import List, Optional
from urllib.request import URLError, urlopen

import ops.charm
import yaml
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v0.systemd import service_resume, service_running
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    WaitingStatus,
)

from mongod_helpers import (
    MONGODB_PORT,
    ConfigurationError,
    ConnectionFailure,
    MongoDB,
    OperationFailure,
)

logger = logging.getLogger(__name__)

PEER = "mongodb"
REPO_URL = "deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"
REPO_ENTRY = (
    "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/5.0 multiverse"
)
GPG_URL = "https://www.mongodb.org/static/pgp/server-5.0.asc"


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

        # handle removal of replica
        self.framework.observe(self.on.mongodb_storage_detaching, self._on_mongodb_remove_replica)
        # if a new leader has been elected update hosts of MongoDB
        self.framework.observe(self.on.leader_elected, self._update_hosts)
        # when a unit departs the replica set update the hosts of MongoDB
        self.framework.observe(self.on.mongodb_relation_departed, self._update_hosts)

    def _update_hosts(self, _) -> None:
        """Update replica set hosts."""
        # allow leader to reset which hosts are being used
        if self.unit.is_leader():
            self._peers.data[self.app]["replica_set_hosts"] = json.dumps(self._unit_ips)

    def _on_mongodb_remove_replica(self, event: ops.charm.StorageDetachingEvent) -> None:
        """Removes unit from the MongoDB replica set config and steps down primary if necessary.

        Args:
            event: The triggering storage detaching event.
        """
        # only remove and reconfigure if all replicas of MongoDB application are in ready state
        if not self._mongo.all_replicas_ready():
            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
            logger.debug("waiting for all replica set hosts to be ready")
            event.defer()
            return

        # if the unit that is leaving is the primary allow it to step down
        logger.debug("current primary is %s. current unit is %s", self._primary, self.unit.name)
        if self.unit.name == self._primary:
            try:
                self._mongo.primary_step_down()
                logger.debug("the current primary is %s", self._primary)
            except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
                logger.error(
                    "deferring removal of unit: %s for reason: %s", self.unit.name, str(e)
                )
                self.unit.status = WaitingStatus("waiting to reconfigure replica set")
                event.defer()
                return

        # reconfigure the replica set without this unit
        try:
            self._mongo.remove_replica(remove_replica_ip=self._unit_ip(self.unit))
            logger.debug("Replica set successfully reconfigured")
            self.unit.status = ActiveStatus()
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            logger.error("deferring removal of unit: %s for reason: %s", self.unit.name, str(e))
            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
            event.defer()
            return

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
        mongo_peer = self._single_mongo_replica(calling_unit_ip)
        if not mongo_peer.is_mongod_ready():
            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
            logger.debug(
                "unit is not ready, cannot initialise replica set unit: %s is ready, deferring on relation-joined",
                calling_unit.name,
            )
            event.defer()
            return

        # only reconfigure if all current replicas of MongoDB application are in ready state
        if not self._mongo.all_replicas_ready():
            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
            logger.debug("waiting for all replica set hosts to be ready")
            event.defer()
            return

        logger.debug("unit: %s is ready to join the replica set", calling_unit.name)
        self._reconfigure(event)

    def _reconfigure(self, event: ops.charm.RelationEvent) -> None:
        """Adds/removes RelationEvent triggering unit from the replica set.

        Note: Removal funcationality will be implemented in the following PR.

        Args:
            event: The triggering relation event.
        """
        # check if reconfiguration is necessary
        if not self._need_replica_set_reconfiguration:
            self.unit.status = ActiveStatus()
            return

        try:
            self._mongo.reconfigure_replica_set()
            # update the set of replica set hosts
            self._peers.data[self.app]["replica_set_hosts"] = json.dumps(self._unit_ips)
            logger.debug("Replica set successfully reconfigured")
            self.unit.status = ActiveStatus()
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            logger.error("deferring reconfigure of replica set: %s", str(e))
            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
            event.defer()

    def _on_install(self, _) -> None:
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

    def _on_config_changed(self, _) -> None:
        """Event handler for configuration changed events."""
        # TODO
        # - update existing mongo configurations based on user preferences
        # - add additional configurations as according to spec doc
        with open("/etc/mongod.conf", "r") as mongo_config_file:
            mongo_config = yaml.safe_load(mongo_config_file)

        machine_ip = self._unit_ip(self.unit)
        mongo_config["net"]["bindIp"] = "localhost,{}".format(machine_ip)
        if "replication" not in mongo_config:
            mongo_config["replication"] = {}

        mongo_config["replication"]["replSetName"] = "rs0"
        with open("/etc/mongod.conf", "w") as mongo_config_file:
            yaml.dump(mongo_config, mongo_config_file)

    def _on_start(self, event: ops.charm.StartEvent) -> None:
        """Enables MongoDB service and initialises replica set.

        Args:
            event: The triggering start event.
        """
        # start mongo service
        self.unit.status = MaintenanceStatus("starting MongoDB")
        if not service_running("mongod.service"):
            logger.debug("starting mongod.service")
            mongod_enabled = service_resume("mongod.service")
            if not mongod_enabled:
                logger.error("failed to enable mongod.service")
                self.unit.status = BlockedStatus("couldn't start MongoDB")
                return

        try:
            self._open_port_tcp(self._port)
        except subprocess.CalledProcessError:
            self.unit.status = BlockedStatus("failed to open TCP port for MongoDB")
            return

        # check if this unit's deployment of MongoDB is ready
        if not self._mongo.is_mongod_ready():
            logger.debug("mongoDB not ready, deferring on start event")
            self.unit.status = WaitingStatus("waiting for MongoDB to start")
            event.defer()
            return

        # mongod is now active
        self.unit.status = ActiveStatus()

        # only leader should initialise the replica set
        if not self.unit.is_leader():
            return

        # initialise replica set if not already a replica set
        if not self._mongo.is_replica_set():
            self._initialise_replica_set()

        # verify that leader is in replica set mode
        if not self._mongo.is_replica_set() or not self._mongo.is_replica_ready():
            logger.debug("Replica set for leader is not ready")
            self.unit.status = WaitingStatus("waiting to initialise replica set")
            event.defer()
            return

        # replica set initialised properly and ready to go
        self.unit.status = ActiveStatus()

    def _on_update_status(self, _):
        # if unit is primary then update status
        if self._primary == self.unit.name:
            self.unit.status = ActiveStatus("Replica set primary")

    def _on_get_primary_action(self, event: ops.charm.ActionEvent):
        event.set_results({"replica-set-primary": self._primary})

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

    def _initialise_replica_set(self) -> None:
        # initialise as a replica set with one replica
        self.unit.status = MaintenanceStatus("initialising MongoDB replica set")
        logger.debug("initialising replica set for leader")
        try:
            leader_ip = self._unit_ip(self.unit)
            self._mongo.initialise_replica_set([leader_ip])
            self._peers.data[self.app]["replica_set_hosts"] = json.dumps([leader_ip])
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            logger.error("error initialising replica sets in _on_start: error: %s", str(e))
            self.unit.status = WaitingStatus("waiting to initialise replica set")

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
        # get IP of current priamry
        try:
            primary_ip = self._mongo.primary()
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
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
        return json.loads(self._peers.data[self.app].get("replica_set_hosts", "[]"))

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
            "root_password": "password",
            "security_key": "",
            "unit_ips": self._unit_ips,
            "replica_set_hosts": self._replica_set_hosts,
            "calling_unit_ip": self._unit_ip(self.unit),
        }
        return config

    @property
    def _mongo(self) -> MongoDB:
        """Fetch the MongoDB server interface object.

        Returns:
            A MongoDB server object.
        """
        return MongoDB(self._config)

    @property
    def _peers(self) -> Optional[Relation]:
        """Fetch the peer relation.

        Returns:
             An `ops.model.Relation` object representing the peer relation.
        """
        return self.model.get_relation(PEER)


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""

    pass


if __name__ == "__main__":
    main(MongodbOperatorCharm)
