# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manager for handling Kafka in-place upgrades."""

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
from charms.mongodb.v0.mongodb import MongoDBConfiguration, MongoDBConnection
from ops.charm import CharmBase
from ops.model import ActiveStatus
from pydantic import BaseModel
from typing_extensions import override

from config import Config

logger = logging.getLogger(__name__)

WRITE_KEY = "write_value"

# The unique Charmhub library identifier, never change it
LIBID = "todo123"

# Increment this major API version when introducing breaking changes
LIBAPI = 1

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 0


class MongoDBDependencyModel(BaseModel):
    """Model for Kafka Operator dependencies."""

    mongod_service: DependencyModel
    # in future have a mongos service here too


class MongoDBUpgrade(DataUpgrade):
    """Implementation of :class:`DataUpgrade` overrides for in-place upgrades."""

    def __init__(self, charm: CharmBase, **kwargs):
        super().__init__(charm, **kwargs)
        self.charm = charm

    @override
    def pre_upgrade_check(self) -> None:
        """Verifies that an upgrade can be done on the MongoDB deployment."""
        default_message = "Pre-upgrade check failed and cannot safely upgrade"

        if self.charm.is_role(Config.Role.SHARD):
            raise ClusterNotReadyError(
                message=default_message, cause="Cannot run pre-upgrade check on shards"
            )

        if not self.is_cluster_healthy():
            raise ClusterNotReadyError(message=default_message, cause="Cluster is not healthy")

        if not self.is_cluster_able_to_read_write():
            raise ClusterNotReadyError(message=default_message, cause="Cluster cannot read/write")

        # Future PR - sharding based checks

    @override
    def build_upgrade_stack(self) -> list[int]:
        """Builds an upgrade stack, specifying the order of nodes to upgrade.

        TODO Implement in DPE-3940
        """

    @override
    def log_rollback_instructions(self) -> None:
        """Logs the rollback instructions in case of failure to upgrade.

        TODO Implement in DPE-3940
        """

    @override
    def _on_upgrade_granted(self, event: UpgradeGrantedEvent) -> None:
        """Execute a series of upgrade steps.

        TODO Implement in DPE-3940
        """

    def is_cluster_healthy(self) -> bool:
        """Returns True if all nodes in the cluster/replcia set are healthy."""
        if self.charm.is_role(Config.Role.SHARD):
            logger.debug("Cannot run full cluster health check on shards")
            return False

        charm_status = self.charm.process_statuses()
        return self.are_nodes_healthy() and isinstance(charm_status, ActiveStatus)

    def are_nodes_healthy(self) -> bool:
        """Returns True if all nodes in the MongoDB deployment are healthy."""
        if self.charm.is_role(Config.Role.CONFIG_SERVER):
            # TODO future PR implement this
            pass

        if self.charm.is_role(Config.Role.REPLICATION):
            with MongoDBConnection(self.charm.mongodb_config) as mongod:
                rs_status = mongod.get_replset_status()
                rs_status = mongod.client.admin.command("replSetGetStatus")
                return not mongod.is_any_sync(rs_status)

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
        # add write to primary
        self.add_write(self.charm.mongodb_config, collection_name, write_value)

        # verify writes on secondaries
        with MongoDBConnection(self.charm.mongodb_config) as mongod:
            primary_ip = mongod.primary()

        replica_ips = set(self.charm._unit_ips)
        secondary_ips = replica_ips - set(primary_ip)
        for secondary_ip in secondary_ips:
            if not self.is_excepted_write_on_replica(secondary_ip, collection_name, write_value):
                # do not return False immediately - as it is
                logger.debug("Secondary with IP %s, does not contain the expected write.")
                self.clear_tmp_collection(collection_name)
                return False

        self.clear_tmp_collection(self.charm.mongodb_config, collection_name)
        return True

    def is_sharded_cluster_able_to_read_write(self) -> bool:
        """Returns True if is possible to write each shard and read value from all nodes.

        TODO: Implement in a future PR.
        """
        return False

    def clear_tmp_collection(
        self, mongodb_config: MongoDBConfiguration, collection_name: str
    ) -> None:
        """Clears the temporary collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            db.drop_collection(collection_name)

    def is_excepted_write_on_replica(
        self, host: str, collection: str, expected_write_value: str
    ) -> bool:
        """Returns True if the replica contains the expected write in the provided collection."""
        secondary_config = self.charm.mongodb_config
        secondary_config.hosts = {host}
        with MongoDBConnection(secondary_config, direct=True) as direct_seconary:
            db = direct_seconary.client["admin"]
            test_collection = db[collection]
            query = test_collection.find({}, {WRITE_KEY: 1})
            return query[0][WRITE_KEY] == expected_write_value

    def get_random_write_and_collection(self) -> Tuple[str, str]:
        """Returns a tutple for a random collection name and a unique write to add to it."""
        choices = string.ascii_letters + string.digits
        collection_name = "collection_" + "".join([secrets.choice(choices) for _ in range(16)])
        write_value = "unique_write_" + "".join([secrets.choice(choices) for _ in range(16)])
        return (collection_name, write_value)

    def add_write(
        self, mongodb_config: MongoDBConfiguration, collection_name, write_value
    ) -> None:
        """Adds a the provided write to the admin database with the provided collection."""
        with MongoDBConnection(mongodb_config) as mongod:
            db = mongod.client["admin"]
            test_collection = db[collection_name]
            write = {WRITE_KEY: write_value}
            test_collection.insert_one(write)
