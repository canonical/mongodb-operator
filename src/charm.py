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

    def _on_mongodb_relation_handler(self, event: ops.charm.RelationEvent) -> None:
        """Adds the unit as a replica to the MongoDB replica set.

        Args:
            event: The triggering relation joined/changed event.
        """
        # only leader should configure replica set
        if not self.unit.is_leader():
            return

        # app-changed-events can trigger the relation changed hook resulting in no JUJU_REMOTE_UNIT
        if event.unit is None:
            return

        #  only add the calling unit to the replica set if it has mongod running
        calling_unit = event.unit
        calling_unit_ip = str(self._peers.data[calling_unit].get("private-address"))
        mongo_peer = self._single_mongo_replica(calling_unit_ip)
        if not mongo_peer.is_ready(standalone=True):
            logger.debug(
                "unit is not ready, cannot initialise replica set unit: %s is ready, deferring on relation-joined",
                calling_unit.name,
            )
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
        if self._need_replica_set_reconfiguration:
            try:
                # reconfigure replica set
                self._mongo.reconfigure_replica_set()
                # update the set of replica set hosts
                self._peers.data[self.app]["replica_set_hosts"] = json.dumps(self._unit_ips)
                logger.debug("Replica set successfully reconfigured")
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
        self._add_mongodb_org_repository()
        self._install_apt_packages(["mongodb-org"])

    def _on_config_changed(self, _) -> None:
        """Event handler for configuration changed events."""
        # TODO
        # - update existing mongo configurations based on user preferences
        # - add additional configurations as according to spec doc
        with open("/etc/mongod.conf", "r") as mongo_config_file:
            mongo_config = yaml.safe_load(mongo_config_file)

        machine_ip = str(self.model.get_binding(PEER).network.bind_address)
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
        if not self._mongo.is_ready(standalone=True):
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
        if not self._mongo.is_ready(standalone=True) or not self._mongo.is_replica_set():
            logger.debug("Replica set for leader is not ready")
            event.defer()
            return

        # replica set initialised properly and ready to go
        self.unit.status = ActiveStatus()

    def _on_update_status(self, _):
        # connect to client for this single unit
        mongod_unit = self._single_mongo_replica(
            str(self.model.get_binding(PEER).network.bind_address)
        )

        # if unit is primary then update status
        if mongod_unit._is_primary:
            self.unit.status = ActiveStatus("Replica set primary")

    def _on_get_primary_action(self, event: ops.charm.ActionEvent):
        # check if current unit is the primary unit
        mongod_unit = self._single_mongo_replica(
            str(self.model.get_binding(PEER).network.bind_address)
        )

        # if unit is primary display this information and exit
        if mongod_unit._is_primary:
            event.set_results({"replica-set-primary": self.unit.name})
            return

        # loop through peers and check if one is the primary
        for unit in self._peers.units:
            # set up a mongo client for this single replica
            mongod_unit = self._single_mongo_replica(
                str(self._peers.data[unit].get("private-address"))
            )

            # if unit is primary display this information and exit
            if mongod_unit._is_primary:
                event.set_results({"replica-set-primary": unit.name})
                return

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

    def _add_mongodb_org_repository(self) -> None:
        """Adds MongoDB repo to container."""
        repositories = apt.RepositoryMapping()

        # Get GPG key
        try:
            key = urlopen("https://www.mongodb.org/static/pgp/server-5.0.asc").read().decode()
        except URLError as e:
            logger.exception("failed to get GPG key, reason: %s", e)
            self.unit.status = BlockedStatus("couldn't install MongoDB")
            return

        # Add the repository if it doesn't already exist
        repo_name = "deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"
        if repo_name not in repositories:
            try:
                line = "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/5.0 multiverse"
                repo = apt.DebianRepository.from_repo_line(line)
                # Import the repository's key
                repo.import_key(key)
                repositories.add(repo)
            except apt.InvalidSourceError as e:
                logger.error("failed to add repository, invalid source: %s", str(e))
                self.unit.status = BlockedStatus("couldn't install MongoDB")
                return
            except ValueError as e:
                logger.exception("failed to add repository: %s", str(e))
                self.unit.status = BlockedStatus("couldn't install MongoDB")
                return

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
            leader_ip = str(self.model.get_binding(PEER).network.bind_address)
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

    @property
    def _need_replica_set_reconfiguration(self) -> bool:
        """Does MongoDB replica set need reconfiguration.

        Returns:
            bool: that indicates if the replica set hosts should be reconfigured
        """
        # are the units for the application all assigned to a host
        return set(self._unit_ips) != set(self._replica_set_hosts)

    @property
    def _check_unit_count(self) -> bool:
        all_units_joined = self.app.planned_units() == len(self._peers.units) + 1
        logger.debug(
            "planned units does not match joined units: %s != %s",
            str(self.app.planned_units()),
            str(len(self._peers.units) + 1),
        )
        return all_units_joined

    @property
    def _unit_ips(self) -> List[str]:
        """Retrieve IP addresses associated with MongoDB application.

        Returns:
            a list of IP address associated with MongoDB application.
        """
        peer_addresses = [
            str(self._peers.data[unit].get("private-address")) for unit in self._peers.units
        ]

        logger.debug("peer addresses: %s", peer_addresses)
        self_address = str(self.model.get_binding(PEER).network.bind_address)
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
            "calling_unit_ip": str(self.model.get_binding(PEER).network.bind_address),
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

    @property
    def _number_of_expected_units(self) -> int:
        """Returns the number of units expect for MongoDB application."""
        return self.app.planned_units()

    @property
    def _number_of_current_units(self) -> int:
        """Returns the number of units in the MongoDB application."""
        return len(self._peers.units) + 1


if __name__ == "__main__":
    main(MongodbOperatorCharm)
