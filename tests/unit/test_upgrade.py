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
    @patch("charm.get_charm_revision")
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_rel_id = self.harness.add_relation("database-peers", "database-peers")
        self.peer_rel_id = self.harness.add_relation("upgrade-version-a", "upgrade-version-a")

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.get_charm_revision")
    @patch("charm.MongoDBStatusHandler.is_status_related_to_mismatched_revision")
    @patch("charm.MongoDBStatusHandler.are_all_units_ready_for_upgrade")
    @patch("charms.mongodb.v0.set_status.MongoDBConnection")
    @patch("charms.mongodb.v0.upgrade_helpers.MongoDBConnection")
    @patch("charms.mongodb.v1.mongodb.MongoDBConnection.is_any_sync")
    def test_is_cluster_healthy(
        self,
        is_any_sync,
        connection,
        connection_ready,
        are_all_units_active,
        get_rev,
        is_status_related_to_mismatched_revision,
    ):
        """Test is_cluster_healthy function."""

        def is_shard_mock_call(*args):
            return args == ("shard",)

        def is_replication_mock_call(*args):
            return args == ("replication",)

        is_status_related_to_mismatched_revision.return_value = False
        active_status = mock.Mock()
        active_status.return_value = ActiveStatus()

        blocked_status = mock.Mock()
        blocked_status.return_value = BlockedStatus()

        mock_units_ready = mock.Mock()
        mock_units_ready.return_value = True
        self.harness.charm.status.are_all_units_ready_for_upgrade = mock_units_ready

        # case 1: unit is not ready after restarting
        connection_ready.return_value.__enter__.return_value.is_ready = False
        assert not self.harness.charm.upgrade.is_cluster_healthy()

        # case 2: cluster is still syncing
        connection_ready.return_value.__enter__.return_value.is_ready = True
        self.harness.charm.is_role = is_replication_mock_call
        self.harness.charm.process_statuses = active_status
        is_any_sync.return_value = True
        assert not self.harness.charm.upgrade.is_cluster_healthy()

        # case 3: unit is not active
        self.harness.charm.process_statuses = blocked_status
        is_any_sync.return_value = False
        assert not self.harness.charm.upgrade.is_cluster_healthy()

        # case 4: cluster is helathy
        self.harness.charm.process_statuses = active_status
        connection.return_value.__enter__.return_value.is_any_sync.return_value = False
        assert self.harness.charm.upgrade.is_cluster_healthy()

        # case 5: not all units are active
        self.harness.charm.status.are_all_units_ready_for_upgrade.return_value = False
        assert not self.harness.charm.upgrade.is_cluster_healthy()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.upgrade_helpers.MongoDBConnection")
    @patch("charm.MongoDBUpgrade.is_write_on_secondaries")
    def test_is_replica_set_able_read_write(self, is_write_on_secondaries, connection):
        """Test test_is_replica_set_able_read_write function."""
        # case 1: writes are not present on secondaries
        is_write_on_secondaries.return_value = False
        assert not self.harness.charm.upgrade.is_replica_set_able_read_write()

        # case 2: writes are present on secondaries
        is_write_on_secondaries.return_value = True
        assert self.harness.charm.upgrade.is_replica_set_able_read_write()
