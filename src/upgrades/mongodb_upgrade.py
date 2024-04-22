# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling MongoDB in-place upgrades."""

import logging
import secrets
import string
from typing import Tuple

from charms.mongodb.v0.mongodb import (
    FailedToMovePrimaryError,
    MongoDBConfiguration,
    MongoDBConnection,
    NotReadyError,
)
from ops.charm import CharmBase
from ops.framework import Object
from ops.model import ActiveStatus
from pymongo.errors import OperationFailure, PyMongoError, ServerSelectionTimeoutError

from config import Config

logger = logging.getLogger(__name__)


WRITE_KEY = "write_value"
UPGRADE_RELATION = "upgrade"


class MongoDBUpgrade(Object):
    """Handlers for upgrade events."""

    def __init__(self, charm: CharmBase):
        self.charm = charm
        super().__init__(charm, UPGRADE_RELATION)
        self.framework.observe(self.charm.on.pre_upgrade_check_action, self.on_pre_upgrade_check)

    def on_pre_upgrade_check(self, event) -> None:
        """Verifies that an upgrade can be done on the MongoDB deployment."""
        # TODO Future PR - integrate this into the juju refresh procedure as to automatically run.
        if not self.charm.unit.is_leader():
            event.fail(
                "Cannot run pre-upgrade check on non-leader units, run this action on the leader unit."
            )
            return

        if self.charm.is_role(Config.Role.SHARD):
            event.fail(
                "Cannot run pre-upgrade check on shards, run this action on the related config-server."
            )
            return

        if not self.is_cluster_healthy():
            event.fail(
                "Cluster is not healthy, do not proceed with ugprade. Please check juju debug for information."
            )
            return

        # We do not get to decide the order of units to upgrade, so we move the primary to the
        # last unit to upgrade. This prevents the primary from jumping around from unit to unit
        # during the upgrade procedure.
        try:
            self.move_primary_to_last_upgrade_unit()
        except (NotReadyError, FailedToMovePrimaryError):
            event.fail(
                "Cluster failed to move primary before re-election. do not proceed with ugprade."
            )

        if not self.is_cluster_able_to_read_write():
            event.fail(
                "Cluster is not healthy cannot read/write to replicas, do not proceed with ugprade. Please check juju debug for information."
            )

        event.set_results({"message": "Pre-upgrade check successful. Proceed with ugprade."})

    def move_primary_to_last_upgrade_unit(self) -> None:
        """Moves the primary to last unit that gets upgraded (the unit with the lowest id).

        Raises:
            NotReadyError, FailedToMovePrimaryError
        """
        lowest_unit = self.charm.unit
        lowest_unit_id = self.charm.unit.name.split("/")[1]
        for unit in self.charm.peers.units:
            if unit.name.split("/")[1] < lowest_unit_id:
                lowest_unit = unit
                lowest_unit_id = unit.name.split("/")[1]

        last_unit_upgraded_ip = self.charm._unit_ip(lowest_unit)
        with MongoDBConnection(self.charm.mongodb_config) as mongod:
            mongod.move_primary(f"{last_unit_upgraded_ip}:{Config.MONGODB_PORT}")

    def is_cluster_healthy(self) -> bool:
        """Returns True if all nodes in the cluster/replcia set are healthy."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.debug("Cannot run full cluster health check on shards")
            return False

        # TODO Future PR - find a way to check shard statuses from config-server
        all_units = self.charm.peers.units
        all_units.add(self.charm.unit)

        not_all_units_active = any(
            not isinstance(self.charm.process_statuses(unit), ActiveStatus) for unit in all_units
        )

        return self.are_nodes_healthy() and not not_all_units_active

    def are_nodes_healthy(self) -> bool:
        """Returns True if all nodes in the MongoDB deployment are healthy."""
        try:
            if self.charm.is_role(Config.Role.CONFIG_SERVER):
                # TODO Future PR - implement node healthy check for sharded cluster
                pass
            if self.charm.is_role(Config.Role.REPLICATION):
                return self.are_replica_set_nodes_healthy(self.charm.mongodb_config)
        except (PyMongoError, OperationFailure, ServerSelectionTimeoutError) as e:
            logger.debug(
                "Cannot proceed with upgrade. Failed to check cluster health, error: %s", e
            )
            return False

    def are_replica_set_nodes_healthy(self, mongodb_config: MongoDBConfiguration) -> bool:
        """Returns true if all nodes in the MongoDB replica set are healthy."""
        with MongoDBConnection(mongodb_config) as mongod:
            rs_status = mongod.get_replset_status()
            rs_status = mongod.client.admin.command("replSetGetStatus")
            return not mongod.is_any_sync(rs_status)

    def is_cluster_able_to_read_write(self) -> bool:
        """Returns True if read and write is feasible for cluster."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.debug("Cannot run read/write check on shard, must run via config-server.")
            return False
        elif self.charm.is_role(Config.Role.CONFIG_SERVER):
            # TODO Future PR - implement node healthy check for sharded cluster
            pass
        else:
            return self.is_replica_set_able_read_write()

    def is_replica_set_able_read_write(self) -> bool:
        """Returns True if is possible to write to primary and read from replicas."""
        collection_name, write_value = self.get_random_write_and_collection()
        self.add_write_to_replica_set(self.charm.mongodb_config, collection_name, write_value)
        write_replicated = self.is_write_on_secondaries(
            self.charm.mongodb_config, collection_name, write_value
        )
        self.clear_tmp_collection(self.charm.mongodb_config, collection_name)
        return write_replicated

    def clear_tmp_collection(
        self, mongodb_config: MongoDBConfiguration, collection_name: str
    ) -> None:
        """Clears the temporary collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            db.drop_collection(collection_name)

    def is_excepted_write_on_replica(
        self,
        host: str,
        db_name: str,
        collection: str,
        expected_write_value: str,
        secondary_config: MongoDBConfiguration,
    ) -> bool:
        """Returns True if the replica contains the expected write in the provided collection."""
        secondary_config.hosts = {host}
        with MongoDBConnection(secondary_config, direct=True) as direct_seconary:
            db = direct_seconary.client[db_name]
            test_collection = db[collection]
            query = test_collection.find({}, {WRITE_KEY: 1})
            return query[0][WRITE_KEY] == expected_write_value

    def get_random_write_and_collection(self) -> Tuple[str, str]:
        """Returns a tutple for a random collection name and a unique write to add to it."""
        choices = string.ascii_letters + string.digits
        collection_name = "collection_" + "".join([secrets.choice(choices) for _ in range(32)])
        write_value = "unique_write_" + "".join([secrets.choice(choices) for _ in range(16)])
        return (collection_name, write_value)

    def add_write_to_replica_set(
        self, mongodb_config: MongoDBConfiguration, collection_name, write_value
    ) -> None:
        """Adds a the provided write to the admin database with the provided collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            test_collection = db[collection_name]
            write = {WRITE_KEY: write_value}
            test_collection.insert_one(write)

    def is_write_on_secondaries(
        self,
        mongodb_config: MongoDBConfiguration,
        collection_name,
        expected_write_value,
        db_name: str = "admin",
    ):
        """Returns true if the expected write."""
        with MongoDBConnection(mongodb_config) as mongod:
            primary_ip = mongod.primary()

        replica_ips = mongodb_config.hosts
        secondary_ips = replica_ips - set(primary_ip)
        for secondary_ip in secondary_ips:
            if not self.is_excepted_write_on_replica(
                secondary_ip, db_name, collection_name, expected_write_value, mongodb_config
            ):
                # do not return False immediately - as it is
                logger.debug("Secondary with IP %s, does not contain the expected write.")
                return False

        return True
