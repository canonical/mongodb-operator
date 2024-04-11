# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch

from charms.data_platform_libs.v0.upgrade import ClusterNotReadyError
from charms.operator_libs_linux.v1 import snap
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.testing import Harness
from tenacity import stop_after_attempt

from charm import MongodbOperatorCharm

from .helpers import patch_network_get


class TestCharm(unittest.TestCase):
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_rel_id = self.harness.add_relation("database-peers", "database-peers")
        self.peer_rel_id = self.harness.add_relation("upgrade", "upgrade")

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.upgrade.MongoDBConnection")
    def test_is_cluster_healthy(self, connection):
        """Test is_cluster_healthy function."""

        def is_shard_mock_call(*args):
            if args == ("shard",):
                return True
            else:
                return False

        def is_replication_mock_call(*args):
            if args == ("replication",):
                return True
            else:
                return False

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
    @patch("charms.mongodb.v0.upgrade.MongoDBConnection")
    @patch("charm.MongoDBUpgrade.is_excepted_write_on_replica")
    def test_is_replica_set_able_read_write(self, is_excepted_write_on_replica, connection):
        """Test test_is_replica_set_able_read_write function."""
        # case 1: writes are not present on secondaries
        is_excepted_write_on_replica.return_value = False
        assert not self.harness.charm.upgrade.is_replica_set_able_read_write()

        # case 2: writes are present on secondaries
        is_excepted_write_on_replica.return_value = True
        assert self.harness.charm.upgrade.is_replica_set_able_read_write()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_build_upgrade_stack(self, connection):
        """Tests that build upgrade stack puts the primary unit at the bottom of the stack."""
        rel_id = self.harness.charm.model.get_relation("database-peers").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        connection.return_value.__enter__.return_value.primary.return_value = "1.1.1.1"
        assert self.harness.charm.upgrade.build_upgrade_stack() == [0, 1]

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.upgrade.Retrying")
    @patch("charm.MongoDBUpgrade.is_excepted_write_on_replica")
    @patch("charm.MongodbOperatorCharm.restart_charm_services")
    @patch("charms.mongodb.v0.upgrade.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm.install_snap_packages")
    @patch("charm.MongodbOperatorCharm.stop_charm_services")
    def test_on_upgrade_granted(
        self,
        stop_charm_services,
        install_snap_packages,
        connection,
        restart,
        is_excepted_write_on_replica,
        retrying,
    ):
        # upgrades need a peer relation to proceed
        rel_id = self.harness.charm.model.get_relation("database-peers").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")

        # case 1: the upgrade is not supported (i.e. mismatch in versions
        connection.return_value.__enter__.return_value.get_mongod_version.return_value = "3.4.5"
        mock_event = MagicMock()
        self.harness.charm.upgrade._on_upgrade_granted(mock_event)
        restart.assert_not_called()

        # case 2: fails to install snap_packages
        connection.return_value.__enter__.return_value.get_mongod_version.return_value = "6.0.5-5"
        install_snap_packages.side_effect = snap.SnapError
        mock_event = MagicMock()
        self.harness.charm.upgrade._on_upgrade_granted(mock_event)
        restart.assert_not_called()

        # case 3: post_upgrade_check fails
        connection.return_value.__enter__.return_value.get_mongod_version.return_value = "6.0.5-5"
        install_snap_packages.side_effect = None
        # disable_retry
        retrying.stop = stop_after_attempt(1)
        retrying.side_effect = ClusterNotReadyError(
            "post-upgrade check failed and cannot safely upgrade",
            cause="Cluster cannot read/write",
        )
        mock_event = MagicMock()
        self.harness.charm.upgrade._on_upgrade_granted(mock_event)
        restart.assert_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

        # case 4: everything works
        connection.return_value.__enter__.return_value.get_mongod_version.return_value = "6.0.5-5"
        install_snap_packages.side_effect = None
        is_excepted_write_on_replica.return_value = True
        retrying.stop = stop_after_attempt(1)
        retrying.side_effect = None
        mock_event = MagicMock()
        self.harness.charm.upgrade._on_upgrade_granted(mock_event)
        restart.assert_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, MaintenanceStatus))