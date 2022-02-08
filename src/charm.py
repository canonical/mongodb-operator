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

from mongoserver import MONGODB_PORT, ConfigurationError, ConnectionFailure, MongoDB

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

    def _on_install(self, _) -> None:
        """Handle the install event (fired on startup).

        Handles the startup install event -- installs updates the apt cache, installs MongoDB.
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
        """Enables MongoDB service and initializes replica set.

        Args:
            event: The triggering start event.
        """
        if not self.unit.is_leader():
            return

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

        if not self._mongo.is_ready():
            self.unit.status = WaitingStatus("waiting for MongoDB to start")
            event.defer()
            return

        # initialize replica set
        self.unit.status = MaintenanceStatus("initialising MongoDB replicaset")
        logger.debug("initialising replica set")
        try:
            logger.debug("initialising replica set for the following IPs %s", self._unit_ips)
            self._mongo.initialize_replica_set(self._unit_ips)
            self._peers.data[self.app]["replica_set_hosts"] = json.dumps(self._unit_ips)
        except (ConnectionFailure, ConfigurationError) as e:
            logger.error("error initialising replica sets in _on_start: error: %s", str(e))
            self.unit.status = BlockedStatus("failed to initialise replicaset")
            return

        self.unit.status = ActiveStatus()

    def _open_port_tcp(self, port: int) -> None:
        """Open the given port.

        Args:
            port: The port to open.
        """
        try:
            check_call(["open-port", "{}/TCP".format(port)])
        except subprocess.CalledProcessError as e:
            logger.exception("failed opening port %s", str(e))
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
                # logger.exception("failed to add repository, invalid source: %s", str(e))
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

    @property
    def _unit_ips(self) -> List[str]:
        """Retrieve IP addressses associated with MongoDB application.

        Returns:
            a list of IP address associated with MongoDB application.
        """
        peer_addresses = [
            str(self._peers.data[unit].get("private_address")) for unit in self._peers.units
        ]

        self_address = str(self.model.get_binding(PEER).network.bind_address)
        logger.debug("unit address: %s", self_address)
        addresses = []
        if peer_addresses:
            addresses.extend(peer_addresses)
        addresses.append(self_address)
        return addresses

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
            "num_peers": 1,
            "port": self._port,
            "root_password": "password",
            "security_key": "",
            "unit_ips": self._unit_ips,
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


if __name__ == "__main__":
    main(MongodbOperatorCharm)
