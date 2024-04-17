# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling MongoDB in-place upgrades."""

import logging
import secrets
import string
from typing import Tuple

from charms.data_platform_libs.v0.upgrade import (
    ClusterNotReadyError,
    DataUpgrade,
    DependencyModel,
    UpgradeGrantedEvent,
)
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError, PyMongoError
from charms.mongodb.v1.mongos import MongosConnection, MongosConfiguration
from charms.mongodb.v0.mongodb import MongoDBConfiguration, MongoDBConnection
from charms.operator_libs_linux.v1 import snap
from ops.charm import CharmBase
from ops.model import ActiveStatus
from pydantic import BaseModel
from tenacity import Retrying, retry, stop_after_attempt, wait_fixed
from typing_extensions import override

from config import Config

logger = logging.getLogger(__name__)

WRITE_KEY = "write_value"
MONGOD_SERVICE = "mongod"


ROLLBACK_INSTRUCTIONS = """Unit failed to upgrade and requires manual rollback to previous stable version.
    1. Re-run `pre-upgrade-check` action on the leader unit to enter 'recovery' state
    2. Run `juju refresh` to the previously deployed charm revision
"""


class FailedToElectNewPrimaryError(Exception):
    """Raised when a new primary isn't elected after stepping down."""


class MongoDBDependencyModel(BaseModel):
    """Model for MongoDB Operator dependencies."""

    mongod_service: DependencyModel
    # in future have a mongos service here too


class MongoDBUpgrade(DataUpgrade):
    """Implementation of :class:`DataUpgrade` overrides for in-place upgrades."""

    def __init__(self, charm: CharmBase, **kwargs):
        super().__init__(charm, **kwargs)
        self.charm = charm

    @property
    def idle(self) -> bool:
        """Checks if cluster has completed upgrade.

        Returns:
            True if cluster has completed upgrade. Otherwise False
        """
        return not bool(self.upgrade_stack)

    @override
    def pre_upgrade_check(self) -> None:
        """Verifies that an upgrade can be done on the MongoDB deployment."""
        default_message = "Pre-upgrade check failed and cannot safely upgrade"

        if self.charm.is_role(Config.Role.SHARD):
            raise ClusterNotReadyError(
                message="Cannot run pre-upgrade check on shards, run this action on the related config-server.",
                cause="Cannot run pre-upgrade check on shards",
                resolution="Run this action on config-server.",
            )

        # todo this check doesn't work in config-server
        if not self.is_cluster_healthy():
            raise ClusterNotReadyError(
                message=default_message,
                cause="Cluster is not healthy",
                resolution="Please check juju debug for information",
            )

        if not self.is_cluster_able_to_read_write():
            raise ClusterNotReadyError(
                message=default_message, cause="Cluster cannot read/write - please check logs"
            )

        # Future PR - sharding based checks

    @retry(
        stop=stop_after_attempt(20),
        wait=wait_fixed(1),
        reraise=True,
    )
    def post_upgrade_check(self) -> None:
        """Runs necessary checks validating the unit is in a healthy state after upgrade."""
        if not self.is_cluster_able_to_read_write():
            raise ClusterNotReadyError(
                message="post-upgrade check failed and cannot safely upgrade",
                cause="Cluster cannot read/write",
            )

    @override
    def build_upgrade_stack(self) -> list[int]:
        """Builds an upgrade stack, specifying the order of nodes to upgrade."""
        if self.charm.is_role(Config.Role.CONFIG_SERVER):
            # TODO implement in a future PR a stack for shards and config server
            pass
        elif self.charm.is_role(Config.Role.REPLICATION):
            return self.get_replica_set_upgrade_stack()

    def get_replica_set_upgrade_stack(self) -> list[int]:
        """Builds an upgrade stack, specifying the order of nodes to upgrade.

        MongoDB Specific: The primary should be upgraded last, so the unit with the primary is
        put at the very bottom of the stack.
        """
        upgrade_stack = []
        units = set([self.charm.unit] + list(self.charm.peers.units))  # type: ignore[reportOptionalMemberAccess]
        primary_unit_id = None
        for unit in units:
            unit_id = int(unit.name.split("/")[-1])
            if unit.name == self.charm.primary:
                primary_unit_id = unit_id
                continue

            upgrade_stack.append(unit_id)

        upgrade_stack.insert(0, primary_unit_id)
        return upgrade_stack

    @override
    def log_rollback_instructions(self) -> None:
        """Logs the rollback instructions in case of failure to upgrade."""
        logger.critical(ROLLBACK_INSTRUCTIONS)

    @override
    def _on_upgrade_granted(self, event: UpgradeGrantedEvent) -> None:
        """Execute a series of upgrade steps."""
        # TODO: Future PR - check compatibility of new mongod version with current mongos versions
        self.charm.stop_charm_services()

        try:
            self.charm.install_snap_packages(packages=Config.SNAP_PACKAGES)
        except snap.SnapError:
            logger.error("Unable to install Snap")
            self.set_unit_failed()
            return

        if self.charm.unit.name == self.charm.primary:
            logger.debug("Stepping down current primary, before upgrading service...")
            self.step_down_primary_and_wait_reelection()

        logger.info(f"{self.charm.unit.name} upgrading service...")
        self.charm.restart_charm_services()

        try:
            logger.debug("Running post-upgrade check...")
            self.post_upgrade_check()

            logger.debug("Marking unit completed...")
            self.set_unit_completed()

            # ensures leader gets it's own relation-changed when it upgrades
            if self.charm.unit.is_leader():
                logger.debug("Re-emitting upgrade-changed on leader...")
                self.on_upgrade_changed(event)

        except ClusterNotReadyError as e:
            logger.error(e.cause)
            self.set_unit_failed()

    def step_down_primary_and_wait_reelection(self) -> bool:
        """Steps down the current primary and waits for a new one to be elected."""
        old_primary = self.charm.primary
        with MongoDBConnection(self.charm.mongodb_config) as mongod:
            mongod.step_down_primary()

        for attempt in Retrying(stop=stop_after_attempt(30), wait=wait_fixed(1), reraise=True):
            with attempt:
                new_primary = self.charm.primary
                if new_primary != old_primary:
                    raise FailedToElectNewPrimaryError()

    def is_cluster_healthy(self) -> bool:
        """Returns True if all nodes in the cluster/replcia set are healthy."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.debug("Cannot run full cluster health check on shards")
            return False

        # TODO - find a way to check shard statuses from config-server
        charm_status = self.charm.process_statuses()
        return self.are_nodes_healthy() and isinstance(charm_status, ActiveStatus)

    def are_nodes_healthy(self) -> bool:
        """Returns True if all nodes in the MongoDB deployment are healthy."""
        try:
            if self.charm.is_role(Config.Role.CONFIG_SERVER):
                return self.are_sharded_nodes_healthy()
            if self.charm.is_role(Config.Role.REPLICATION):
                return self.are_replica_set_nodes_healthy(self.charm.mongodb_config)
        except (PyMongoError, OperationFailure, ServerSelectionTimeoutError) as e:
            logger.debug(
                "Cannot proceed with upgrade. Failed to check cluster health, error: %s", e
            )
            return False

    def are_replica_set_nodes_healthy(self, mongodb_config: MongoDBConfiguration) -> bool:
        with MongoDBConnection(mongodb_config) as mongod:
            rs_status = mongod.get_replset_status()
            rs_status = mongod.client.admin.command("replSetGetStatus")
            return not mongod.is_any_sync(rs_status)

    def are_sharded_nodes_healthy(self) -> bool:
        """Returns True if all nodes in the sharded cluster are healthy."""
        # verify all shards are healthy
        if self.charm.config_server.get_unreachable_shards():
            logger.debug("Cannot proceed with upgrade. Not all shards are reachable")
            return False

        with MongosConnection(self.charm.mongos_config) as mongos:
            draining_shards = mongos.get_draining_shards()
            shards = mongos.get_shard_members()

        if draining_shards:
            logger.debug(
                "Cannot proceed with upgrade. Cluster actively draining shards %s", draining_shards
            )
            return False

        # verify that all nodes in shards are healthy
        for shard in shards:
            replica_set_healthy = self.are_replica_set_nodes_healthy(
                self.charm.get_mongodb_config_for_shard(shard)
            )
            if not replica_set_healthy:
                logger.debug(
                    "Cannot proceed with upgrade. Replica set nodes for shard %s are not healthy",
                    shard,
                )
                return False

        return True

    def is_cluster_able_to_read_write(self) -> bool:
        """Returns True if read and write is feasible for cluster."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.debug("Cannot run read/write check on shard, must run via config-server.")
            return False
        elif self.charm.is_role(Config.Role.CONFIG_SERVER):
            return self.is_sharded_cluster_able_to_read_write()
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

    def is_sharded_cluster_able_to_read_write(self) -> bool:
        """Returns True if is possible to write each shard and read value from all nodes."""
        collection_name, _ = self.get_random_write_and_collection()
        db_name = f"db-{collection_name}"

        with MongosConnection(self.charm.mongos_config) as mongos:
            shards = mongos.get_shard_members()

        for shard in shards:
            _, write_value = self.get_random_write_and_collection()
            self.add_write_to_shard(
                self.charm.mongos_config, db_name, collection_name, write_value, shard
            )

            writes_replicated = self.is_write_on_secondaries(
                self.charm.get_mongodb_config_for_shard(shard),
                collection_name,
                write_value,
                f"db-{collection_name}",
            )
            if not writes_replicated:
                logger.debug("Writes not propogated on shard %s", shard)
                break

        self.clear_tmp_db(self.charm.mongos_config, db_name)
        return writes_replicated

    def clear_tmp_collection(
        self, mongodb_config: MongoDBConfiguration, collection_name: str
    ) -> None:
        """Clears the temporary collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            db.drop_collection(collection_name)

    def clear_tmp_db(self, mongos_config: MongosConfiguration, database_name: str) -> None:
        """Clears the temporary database."""
        with MongoDBConnection(mongos_config) as mongos:
            mongos.client.drop_database(database_name)

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

    def add_write_to_shard(
        self,
        mongos_config: MongosConfiguration,
        db_name: str,
        collection_name: str,
        write_value: int,
        shard_name: str,
    ) -> None:
        """Adds a the provided write to the admin database with the provided collection."""
        with MongosConnection(mongos_config) as mongos:
            db = mongos.client[db_name]
            test_collection = db[collection_name]
            write = {WRITE_KEY: write_value}
            test_collection.insert_one(write)

            mongos.client.admin.command("movePrimary", db_name, to=shard_name)

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
        """Returns true if the exepected write"""
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
