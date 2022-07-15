# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class we manage legacy client database relations.

This class is modeled after the legacy machine charm relations, hence it disables auth and exposes
the expected relation data for legacy relations.
"""
import logging
from typing import Optional

from charms.mongodb_libs.v0.machine_helpers import (
    auth_enabled,
    stop_mongod_service,
    start_mongod_service,
    update_mongod_service,
)
from charms.operator_libs_linux.v1 import systemd
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus

from charms.operator_libs_linux.v1 import systemd


# The unique Charmhub library identifier, never change it
LIBID = "9t384yt02t8fj9iecin83r20359ruij"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version.
LIBPATCH = 1

logger = logging.getLogger(__name__)
REL_NAME = "database"

REL_NAME = "database"
LEGACY_REL_NAME = "obsolete"

# We expect the MongoDB container to use the default ports
MONGODB_PORT = 27017
MONGODB_VERSION = "5.0"
PEER = "database-peers"


class MongoDBLegacyProvider(Object):
    """In this class we manage legacy client database relations."""

    def __init__(self, charm):
        """Manager of MongoDB client relations."""
        super().__init__(charm, "client-relations")
        self.charm = charm
        self.framework.observe(
            self.charm.on[LEGACY_REL_NAME].relation_created, self._on_legacy_relation_created
        )
        self.framework.observe(
            self.charm.on[LEGACY_REL_NAME].relation_joined, self._on_legacy_relation_joined
        )

    ################################################################################
    # LEGACY RELATIONS VM
    ################################################################################
    def _on_legacy_relation_created(self, event):
        """Legacy relations for MongoDB operate without a password and so we update the server accordingly and
        set a flag.
        """
        logger.warning("DEPRECATION WARNING - `mongodb` interface is a legacy interface.")

        # legacy relations turn off authentication, therefore disabling authentication for current
        # users (which connect over the new relation interface). If current users exist that use
        # auth it is necessary to not proceed and go into blocked state.
        relation_users = self._get_users_from_relations(departed_relation_id=None)
        if len(relation_users) > 0:
            self.charm.unit.status = BlockedStatus("cannot have both legacy and new relations")
            logger.error(
                "Creating legacy relation would turn off auth effecting the new relations: %s",
                relation_users,
            )
            return

        # If auth is already disabled its likely it has a connection with another legacy relation
        # user. Shutting down and restarting mongod would lead to downtime for the other legacy
        # relation user and hence shouldn't be done. Not to mention there is no need to disable
        # auth if it is already disabled.
        if auth_enabled():
            try:
                logger.debug("Disabling authentication.")
                self.charm.unit.status = MaintenanceStatus("disabling authentication")
                stop_mongod_service()
                update_mongod_service(
                    auth=False,
                    machine_ip=self.charm._unit_ip(self.charm.unit),
                    replset=self.charm.app.name,
                )
                start_mongod_service()
                self.charm.unit.status = ActiveStatus()
            except systemd.SystemdError:
                self.charm.unit.status = BlockedStatus("couldn't restart MongoDB")
                return

    def _on_legacy_relation_joined(self, event):
        """
        NOTE: this is retro-fitted from the legacy mongodb charm:
        https://git.launchpad.net/charm-mongodb/tree/hooks/hooks.py#n1423
        """
        logger.warning("DEPRECATION WARNING - `mongodb` interface is a legacy interface.")

        updates = {
            "hostname": str(self.model.get_binding(PEER).network.bind_address),
            "port": str(MONGODB_PORT),
            "type": "database",
            "version": MONGODB_VERSION,
            "replset": self.charm.app.name,
        }

        # reactive charms set relation data on "the current unit" the reactive mongodb charm sets
        # the relation data for all units, hence all units setting the relation data and not just
        # the leader
        relation = self.model.get_relation(REL_NAME, event.relation.id)
        relation.data[self.charm.unit].update(updates)

    def _get_users_from_relations(self, departed_relation_id: Optional[int], rel=REL_NAME):
        """Return usernames for all relations except departed relation."""
        relations = self.model.relations[rel]
        return set(
            [
                self._get_username_from_relation_id(relation.id)
                for relation in relations
                if relation.id != departed_relation_id
            ]
        )

    @staticmethod
    def _get_username_from_relation_id(relation_id: str) -> str:
        """Construct username."""
        return f"relation-{relation_id}"
