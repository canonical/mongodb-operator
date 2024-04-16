# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest import mock
from unittest.mock import patch

from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import MongodbOperatorCharm

from .helpers import patch_network_get


class TestCharm(unittest.TestCase):
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_rel_id = self.harness.add_relation("database-peers", "database-peers")

    @patch_network_get(private_address="1.1.1.1")
    @patch("events.upgrade.MongoDBConnection")
    def test_is_cluster_healthy(self, connection):
        """Test is_cluster_healthy function."""

        def is_shard_mock_call(*args):
            return args == ("shard",)

        def is_replication_mock_call(*args):
            return args == ("replication",)

        active_status = mock.Mock()
        active_status.return_value = ActiveStatus()

        blocked_status = mock.Mock()
        blocked_status.return_value = BlockedStatus()

        # case 1: running on a shard
        self.harness.charm.is_role = is_shard_mock_call
        assert not self.harness.charm.upgrade.is_cluster_healthy()

        # case 2: cluster is still syncing
        self.harness.charm.is_role = is_replication_mock_call
        self.harness.charm.process_statuses = active_status
        connection.return_value.__enter__.return_value.is_any_sync.return_value = True
        assert not self.harness.charm.upgrade.is_cluster_healthy()

        # case 3: unit is not active
        self.harness.charm.process_statuses = blocked_status
        connection.return_value.__enter__.return_value.is_any_sync.return_value = False
        assert not self.harness.charm.upgrade.is_cluster_healthy()

        # # case 4: cluster is helathy
        self.harness.charm.process_statuses = active_status
        assert self.harness.charm.upgrade.is_cluster_healthy()

    @patch_network_get(private_address="1.1.1.1")
    @patch("events.upgrade.MongoDBConnection")
    @patch("charm.MongoDBUpgrade.is_excepted_write_on_replica")
    def test_is_replica_set_able_read_write(self, is_excepted_write_on_replica, connection):
        """Test test_is_replica_set_able_read_write function."""
        # case 1: writes are not present on secondaries
        is_excepted_write_on_replica.return_value = False
        assert not self.harness.charm.upgrade.is_replica_set_able_read_write()

        # case 2: writes are present on secondaries
        is_excepted_write_on_replica.return_value = True
        assert self.harness.charm.upgrade.is_replica_set_able_read_write()
