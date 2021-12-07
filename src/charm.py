#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
import yaml
import json
import logging
import ops.charm
import subprocess
from subprocess import check_call
from urllib.request import urlopen

from ops.charm import CharmBase
from ops.main import main
from ops.model import BlockedStatus, MaintenanceStatus, WaitingStatus, ActiveStatus, Relation
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v0.systemd import service_restart, service_resume
from mongoserver import MongoDB, MONGODB_PORT
from typing import Optional

logger = logging.getLogger(__name__)

PEER = "mongodb"

class MongodbOperatorCharm(ops.charm.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self.port = MONGODB_PORT

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.start, self._on_start)

    def _on_install(self, _: ops.charm.InstallEvent) -> None:
        """Handle the install event (fired on startup)
        Handles the startup install event -- installs updates the apt cache, installs mongoDB
        Args:
            _ (ops.charm.InstallEvent): The install event that fired.
        Returns:
            None: None
        """
        self.unit.status = MaintenanceStatus("installing MongoDB")
        self._add_mongodb_org_repository()
        self._install_apt_packages(["mongodb-org"])
        try:
            mongo_path = subprocess.check_output(["which", "mongod"]).decode().strip()
            if not mongo_path == "/usr/bin/mongod":
                logger.error("wrong mongodb path found %s want /usr/bin/mongod",mongo_path)
                self.unit.status = BlockedStatus("wrong mongod path")
                return
        except subprocess.CalledProcessError as e:
            logger.error("failed to verify mongod installation %s",e)
            self.unit.status = BlockedStatus("failed to verify mongod installation")
            return
        
    def _on_config_changed(self, _: ops.charm.ConfigChangedEvent) -> None:
        """Event handler for configuration changed events.
        Args:
            _ (ops.charm.ConfigChangedEvent): The configuration changed event
        Returns:
            None: None
        """
        # TODO
        # - update existing mongo configurations based on user preferences 
        # - add additional configurations as according to spec doc
        with open("/etc/mongod.conf") as mongo_config_file:
            mongo_config = yaml.safe_load(mongo_config_file)
            
        machineIP = str(self.model.get_binding(PEER).network.bind_address)
        bindIPs = "localhost,"+machineIP
        mongo_config["net"]["bindIp"] = bindIPs
        if "replication" not in mongo_config:
            mongo_config["replication"] = {}
        
        mongo_config["replication"]["replSetName"] = "rs0"
        with open('/etc/mongod.conf', 'w') as mongo_config_file:
            yaml.dump(mongo_config, mongo_config_file)

        self.unit.status = ops.model.ActiveStatus()

    def _on_start(self, event: ops.charm.StartEvent) -> None:
        """Enables MongoDB service and initializes replica set
        Args:
            event (ops.charm.StartEvent): The triggering start event 
        Returns:
            None: None
        """
        logger.debug("Running on_start")
        if not self.unit.is_leader():
            return

        # start mongo service
        self._open_port_tcp(self.port)
        self.unit.status = MaintenanceStatus("enabling MongoDB")
        try:
            logger.debug("enabling mongodb")
            service_resume("mongod.service")
            service_restart("mongod.service")
        except subprocess.CalledProcessError as e:
            logger.error("failed to enable mongo error: %s", e)
            self.unit.status = BlockedStatus("failed to enable mongo")
            return

        if not self.mongo.is_ready():
            self.unit.status = WaitingStatus("Waiting for MongoDB Service")
            event.defer()
            return

        # initialize replica set
        self.unit.status = MaintenanceStatus("initializing MongoDB replicaset")
        logger.debug("initalizing replica set")
        try:
            logger.debug("initialzing replica set for these IPs %s", self.unit_ips)
            self.mongo.initialize_replica_set(self.unit_ips)
            self.peers.data[self.app][
                "replica_set_hosts"] = json.dumps(self.unit_ips)
        except Exception as e:
            logger.error("Error initializing replica sets in _on_start: error={}".format(e))
            self.unit.status = BlockedStatus("failed to initialize replicasets")
            return
        
        self.unit.status = ActiveStatus("MongoDB started")

    def _open_port_tcp(self, port: int) -> None:
        """Open the given port.
        Args:
            port (int): The port to open
        Returns:
            None: None
        """
        try:
            check_call(["open-port", f"{port}/TCP"])
        except subprocess.CalledProcessError as e:
            logger.exception(f"failed opening port {port}", exc_info=e)
            raise BlockedStatusException(f"failed to open port {port}")

    def _add_mongodb_org_repository(self) -> None:
        """Adds mongoDB repo to container
        Args:
            None: None
        Returns:
            None: None
        """
        repositories = apt.RepositoryMapping()

        # Get GPG key
        try:
            key = urlopen("https://www.mongodb.org/static/pgp/server-5.0.asc").read().decode()
        except Exception as e:
            logger.exception(f"failed to get GPG key", exc_info=e)
            self.unit.status = BlockedStatus("Failed to get GPG key")
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
            except Exception as e:
                logger.exception(f"failed to add repository", exc_info=e)
                self.unit.status = BlockedStatus("Failed to add mongodb repository")
                return

    def _install_apt_packages(self, packages: list):
        """Installs package(s) to container
        Args:
            packages (list): list of packages to install
        Returns:
            None: None
        """
        try:
            logger.debug("updating apt cache")
            apt.update()
        except subprocess.CalledProcessError as e:
            logger.exception(f"failed to update apt cache, CalledProcessError", exc_info=e)
            self.unit.status = BlockedStatus("Failed to update apt cache")
            return

        try:
            logger.debug("installing apt packages: %s", ", ".join(packages))
            apt.add_package(packages)
        except apt.PackageNotFoundError:
            logger.error("a specified package not found in package cache or on system")
            self.unit.status = BlockedStatus("Failed to install packages")
        except Exception as e:
            logger.error("could not install package. Reason: %s", e.message)
            self.unit.status = BlockedStatus("Failed to install packages")

    @property
    def unit_ips(self) -> list:
        """Retrieve IP addressses associated with mongoDB application
        Returns:
            list (str): IP address associated with mongoDB application
        """
        peer_addresses = [
          str(self.peers.data[unit].get("private_address"))
          for unit in self.peers.units
        ]

        self_address = str(self.model.get_binding(PEER).network.bind_address)
        logger.debug("this machines address %s", self_address)  
        addresses = []
        if peer_addresses:
            addresses.extend(peer_addresses)
        addresses.append(self_address)
        return addresses
    
    @property
    def config(self) -> dict:
        """Retrieve config options for mongo
        Returns:
            dict: Config options for mogno
        """
        # TODO parameterize remaining config options
        config = {
            "app_name": self.model.app.name,
            "replica_set_name": "rs0", 
            "num_peers": 1,
            "port": self.port,
            "root_password": "password",
            "security_key": "",
            "unit_ips": self.unit_ips
        }
        return config

    @property
    def mongo(self) -> MongoDB:
        """Fetch the MongoDB server interface object.
        Args: None
        Returns:
            MongoDB: server interface object
        """
        return MongoDB(self.config)

    @property
    def peers(self) -> Optional[Relation]:
        """Fetch the peer relation
        Returns:
             A :class:`ops.model.Relation` object representing
             the peer relation.
        """
        return self.model.get_relation(PEER)

if __name__ == "__main__":
    main(MongodbOperatorCharm)
