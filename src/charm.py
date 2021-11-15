#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
from urllib.request import urlopen

from ops.charm import CharmBase
from ops.main import main
from ops.model import BlockedStatus, MaintenanceStatus, WaitingStatus
from charms.operator_libs_linux.v0 import apt

logger = logging.getLogger(__name__)


class MongodbOperatorCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)

    def _on_install(self, _):
        """Install prerequisites for the application"""
        self.unit.status = MaintenanceStatus("installing MongoDB")
        self._add_mongodb_org_repository()
        self._install_apt_packages(["mongodb-org"])
        self.unit.status = WaitingStatus("Waiting to start MongoDB")

    def _add_mongodb_org_repository(self):
        repositories = apt.RepositoryMapping()

        # Get GPG key
        try:
            key = urlopen("https://www.mongodb.org/static/pgp/server-5.0.asc").read().decode()
        except Exception as e:
            logger.exception(f"failed to get GPG key", exc_info=e)
            self.unit.status = BlockedStatus("Failed to get GPG key")
            return

        # Add the repository if it doesn't already exist
        if "https://repo.mongodb.org/apt/ubuntu" not in repositories:
            try:
                line = "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/5.0 muliverse"
                repo = apt.DebianRepository.from_repo_line(line)
                # Import the repository's key
                repo.import_key(key)
                repositories.add(repo)
            except Exception as e:
                logger.exception(f"failed to add repository", exc_info=e)
                self.unit.status = BlockedStatus("Failed to add mongodb repository")
                return

    def _install_apt_packages(self, packages: list):
        """Simple wrapper around 'apt-get install -y"""
        try:
            logger.debug("updating apt cache")
            apt.update()
        except subprocess.TimeoutExpired as e:
            logger.exception(f"failed to update apt cache, TimeoutExpired", exc_info=e)
            self.unit.status = BlockedStatus("Failed to update apt cache")
            event.defer()
            return
        except Exception as e:
            logger.exception(f"failed to update apt cache", exc_info=e)
            self.unit.status = BlockedStatus("Failed to update apt cache")
            return

        try:
            logger.debug("installing apt packages: %s", ", ".join(packages))
            apt.add_package(packages)
        except apt.PackageNotFoundError:
            logger.error("a specified package not found in package cache or on system")
            self.unit.status = BlockedStatus("Failed to install packages")
        except apt.PackageError as e:
            logger.error("could not install package. Reason: %s", e.message)
            self.unit.status = BlockedStatus("Failed to install packages")


if __name__ == "__main__":
    main(MongodbOperatorCharm)
