# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest import mock
from unittest.mock import call, patch

from charms.operator_libs_linux.v1 import snap
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness
from pymongo.errors import ConfigurationError, ConnectionFailure, OperationFailure
from tenacity import stop_after_attempt

from charm import MongodbOperatorCharm, NotReadyError, subprocess

from .helpers import patch_network_get

REPO_NAME = "deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"
REPO_ENTRY = (
    "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/5.0 multiverse"
)
REPO_MAP = {"deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"}
PEER_ADDR = {"private-address": "127.4.5.6"}

PYMONGO_EXCEPTIONS = [
    ConnectionFailure("error message"),
    ConfigurationError("error message"),
    OperationFailure("error message"),
]

S3_RELATION_NAME = "s3-credentials"


class TestCharm(unittest.TestCase):
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_rel_id = self.harness.add_relation("database-peers", "database-peers")

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_operator_user")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.snap.SnapCache")
    @patch("charm.push_file_to_unit")
    @patch("builtins.open")
    def test_on_start_not_leader_doesnt_initialise_replica_set(
        self, open, path, snap, _open_port_tcp, init_admin, connection
    ):
        """Tests that a non leader unit does not initialise the replica set."""
        # set snap data
        mock_mongodb_snap = mock.Mock()
        mock_mongodb_snap.present = True
        mock_mongodb_snap.start = mock.Mock()
        snap.return_value = {"charmed-mongodb": mock_mongodb_snap}
        self.harness.charm.app_peer_data["monitor-password"] = "pass123"

        self.harness.set_leader(False)
        self.harness.charm.on.start.emit()

        mock_mongodb_snap.start.assert_called()
        _open_port_tcp.assert_called()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        connection.return_value.__enter__.return_value.init_replset.assert_not_called()
        init_admin.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_operator_user")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.push_file_to_unit")
    @patch("builtins.open")
    def test_on_start_snap_failure_leads_to_blocked_status(
        self,
        open,
        path,
        _open_port_tcp,
        init_admin,
        connection,
    ):
        """Test failures on systemd result in blocked status."""
        self.harness.set_leader(True)
        self.harness.charm.on.start.emit()
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))
        _open_port_tcp.assert_not_called()

        connection.return_value.__enter__.return_value.init_replset.assert_not_called()
        init_admin.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.snap.SnapCache")
    @patch("charm.push_file_to_unit")
    @patch("builtins.open")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_operator_user")
    def test_on_start_mongod_not_ready_defer(
        self,
        init_admin,
        connection,
        open,
        path,
        snap,
        initialise_replica_set,
        _open_port_tcp,
    ):
        """Test verifies that we wait to initialise replica set when mongod is not running."""
        # set snap data
        mock_mongodb_snap = mock.Mock()
        mock_mongodb_snap.present = True
        mock_mongodb_snap.start = mock.Mock()
        snap.return_value = {"charmed-mongodb": mock_mongodb_snap}

        self.harness.set_leader(True)
        connection.return_value.__enter__.return_value.is_ready = False

        self.harness.charm.on.start.emit()
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))
        connection.return_value.__enter__.return_value.init_replset.assert_not_called()
        init_admin.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.snap.SnapCache")
    @patch("charm.push_file_to_unit")
    @patch("builtins.open")
    def test_start_unable_to_open_tcp_moves_to_blocked(self, open, path, snap, _open_port_tcp):
        """Test verifies that if TCP port cannot be opened we go to the blocked state."""
        # set snap data
        mock_mongodb_snap = mock.Mock()
        mock_mongodb_snap.present = True
        mock_mongodb_snap.start = mock.Mock()
        snap.return_value = {"charmed-mongodb": mock_mongodb_snap}

        self.harness.set_leader(True)
        _open_port_tcp.side_effect = subprocess.CalledProcessError(
            cmd="open-port 27017/TCP", returncode=1
        )
        self.harness.charm.on.start.emit()

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("failed to open TCP port for MongoDB")
        )

    @patch("subprocess.check_call")
    def test_set_port(self, _call):
        """Test verifies operation of set port."""
        self.harness.charm._open_port_tcp(27017)
        # Make sure the port is opened and the service is started
        self.assertEqual(_call.call_args_list, [call(["open-port", "27017/TCP"])])

    @patch("subprocess.check_call")
    def test_set_port_failure(self, _call):
        """Test verifies that we raise the correct errors when we fail to open a port."""
        _call.side_effect = subprocess.CalledProcessError(cmd="open-port 27017/TCP", returncode=1)

        with self.assertRaises(subprocess.CalledProcessError):
            with self.assertLogs("charm", "ERROR") as logs:
                self.harness.charm._open_port_tcp(27017)
                self.assertIn("failed opening port 27017", "".join(logs.output))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.update_mongod_service")
    @patch("charm.snap.SnapCache")
    @patch("subprocess.check_call")
    def test_install_snap_packages_failure(self, _call, snap_cache, update_mongod_service):
        """Test verifies the correct functions get called when installing apt packages."""
        snap_cache.side_effect = snap.SnapError
        self.harness.charm.on.install.emit()
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch_network_get(private_address="1.1.1.1")
    def test_unit_ips(self):
        rel_id = self.harness.charm.model.get_relation("database-peers").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", PEER_ADDR)

        resulting_ips = self.harness.charm._unit_ips
        expected_ips = ["127.4.5.6", "1.1.1.1"]
        self.assertEqual(resulting_ips, expected_ips)

    @patch("charm.MongoDBConnection")
    def test_mongodb_relation_joined_non_leader_does_nothing(self, connection):
        """Test verifies that non-leader units don't reconfigure the replica set on joined."""
        rel = self.harness.charm.model.get_relation("database-peers")
        self.harness.set_leader(False)
        self.harness.charm.on.database_peers_relation_joined.emit(relation=rel)
        connection.return_value.__enter__.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_mongodb_relation_joined_all_replicas_not_ready(self, _, connection):
        """Tests that we go into waiting when current ReplicaSet hosts are not ready.

        Tests the scenario that if current replica set hosts are not ready, the leader goes into
        WaitingStatus and no attempt to reconfigure is made.
        """
        # preset values
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        connection.return_value.__enter__.return_value.is_ready = False
        connection.return_value.__enter__.return_value.get_replset_members.return_value = {
            "1.1.1.1"
        }

        # simulate 2nd MongoDB unit
        rel = self.harness.charm.model.get_relation("database-peers")
        self.harness.add_relation_unit(rel.id, "mongodb/1")
        self.harness.update_relation_data(rel.id, "mongodb/1", PEER_ADDR)

        # verify we go into waiting and don't reconfigure
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))
        connection.return_value.__enter__.return_value.add_replset_member.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("ops.framework.EventBase.defer")
    @patch("charm.MongoDBConnection")
    @patch("charms.mongodb.v0.mongodb.MongoClient")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_relation_joined_get_members_failure(self, _, client, connection, defer):
        """Tests reconfigure does not execute when unable to get the replica set members.

        Verifies in case of relation_joined and relation departed, that when the the database
        cannot retrieve the replica set members that no attempts to remove/add units are made and
        that the the event is deferred.
        """
        # presets
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        rel = self.harness.charm.model.get_relation("database-peers")

        for exception in PYMONGO_EXCEPTIONS:
            connection.return_value.__enter__.return_value.get_replset_members.side_effect = (
                exception
            )

            # test both relation events
            for departed in [False, True]:
                if departed:
                    # simulate removing 2nd MongoDB unit
                    self.harness.remove_relation_unit(rel.id, "mongodb/1")
                    connection.return_value.__enter__.return_value.add_replset_member.assert_not_called()
                else:
                    # simulate 2nd MongoDB unit joining
                    self.harness.add_relation_unit(rel.id, "mongodb/1")
                    self.harness.update_relation_data(rel.id, "mongodb/1", PEER_ADDR)
                    connection.return_value.__enter__.return_value.remove_replset_member.assert_not_called()

                defer.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("ops.framework.EventBase.defer")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_reconfigure_add_member_failure(self, _, connection, defer):
        """Tests reconfigure does not proceed when unable to add a member.

        Verifies in relation joined events, that when the database cannot add a member that the
        event is deferred.
        """
        # presets
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        connection.return_value.__enter__.return_value.get_replset_members.return_value = {
            "1.1.1.1"
        }
        rel = self.harness.charm.model.get_relation("database-peers")

        exceptions = PYMONGO_EXCEPTIONS
        exceptions.append(NotReadyError)
        for exception in exceptions:
            connection.return_value.__enter__.return_value.add_replset_member.side_effect = (
                exception
            )

            # simulate 2nd MongoDB unit joining( need a unit to join before removing a unit)
            self.harness.add_relation_unit(rel.id, "mongodb/1")
            self.harness.update_relation_data(rel.id, "mongodb/1", PEER_ADDR)

            connection.return_value.__enter__.return_value.add_replset_member.assert_called()
            defer.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.snap.SnapCache")
    @patch("charm.push_file_to_unit")
    @patch("builtins.open")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_operator_user")
    def test_initialise_replica_failure_leads_to_waiting_state(
        self,
        init_admin,
        connection,
        open,
        path,
        snap_cache,
        _,
    ):
        """Tests that failure to initialise replica set goes into Waiting Status."""
        # set snap data
        mock_mongodb_snap = mock.Mock()
        snap.return_value = {"charmed-mongodb": mock_mongodb_snap}

        # set peer data so that leader doesn't reconfigure set on set_leader

        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["_new_leader_must_reconfigure"] = "False"
        connection.return_value.__enter__.return_value.is_ready = True

        for exception in PYMONGO_EXCEPTIONS:
            connection.return_value.__enter__.return_value.init_replset.side_effect = exception
            self.harness.charm.on.start.emit()
            connection.return_value.__enter__.return_value.init_replset.assert_called()
            init_admin.assert_not_called()
            self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.helpers.MongoDBConnection")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.build_unit_status")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_update_status_mongodb_error(
        self, _, get_mongodb_status, get_pbm_status, connection, status_connection
    ):
        """Tests that when MongoDB is not active, that is reported instead of pbm."""
        # assume leader has already initialised the replica set
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        connection.return_value.__enter__.return_value.is_ready = True

        pbm_statuses = [
            ActiveStatus("pbm"),
            BlockedStatus("pbm"),
            MaintenanceStatus("pbm"),
            WaitingStatus("pbm"),
        ]
        mongodb_statuses = [
            BlockedStatus("mongodb"),
            MaintenanceStatus("mongodb"),
            WaitingStatus("mongodb"),
        ]
        self.harness.add_relation(S3_RELATION_NAME, "s3-integrator")

        for pbm_status in pbm_statuses:
            for mongodb_status in mongodb_statuses:
                get_pbm_status.return_value = pbm_status
                get_mongodb_status.return_value = mongodb_status
                self.harness.charm.on.update_status.emit()
                self.assertEqual(self.harness.charm.unit.status, mongodb_status)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.helpers.MongoDBConnection")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.build_unit_status")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_update_status_pbm_error(
        self, _, get_mongodb_status, get_pbm_status, connection, status_connection
    ):
        """Tests when MongoDB is active and pbm is in the error state, pbm status is reported."""
        # assume leader has already initialised the replica set
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        connection.return_value.__enter__.return_value.is_ready = True

        pbm_statuses = [
            BlockedStatus("pbm"),
            MaintenanceStatus("pbm"),
            WaitingStatus("pbm"),
        ]
        mongodb_statuses = [ActiveStatus("mongodb")]
        self.harness.add_relation(S3_RELATION_NAME, "s3-integrator")

        for pbm_status in pbm_statuses:
            for mongodb_status in mongodb_statuses:
                get_pbm_status.return_value = pbm_status
                get_mongodb_status.return_value = mongodb_status
                self.harness.charm.on.update_status.emit()
                self.assertEqual(self.harness.charm.unit.status, pbm_status)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.helpers.MongoDBConnection")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.build_unit_status")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_update_status_pbm_and_mongodb_ready(
        self, _, get_mongodb_status, get_pbm_status, connection, status_connection
    ):
        """Tests when both Mongodb and pbm are ready that MongoDB status is reported."""
        # assume leader has already initialised the replica set
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        connection.return_value.__enter__.return_value.is_ready = True

        self.harness.add_relation(S3_RELATION_NAME, "s3-integrator")

        get_pbm_status.return_value = ActiveStatus("pbm")
        get_mongodb_status.return_value = ActiveStatus("mongodb")
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("mongodb"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.helpers.MongoDBConnection")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.build_unit_status")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_update_status_no_s3(
        self, _, get_mongodb_status, get_pbm_status, connection, status_connection
    ):
        """Tests when the s3 relation isn't present that the MongoDB status is reported."""
        # assume leader has already initialised the replica set
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        connection.return_value.__enter__.return_value.is_ready = True

        get_pbm_status.return_value = BlockedStatus("pbm")
        get_mongodb_status.return_value = ActiveStatus("mongodb")
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("mongodb"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.helpers.MongoDBConnection")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_update_status_primary(self, _, pbm_status, connection, status_connection):
        """Tests that update status identifies the primary unit and updates status."""
        # assume leader has already initialised the replica set
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        pbm_status.return_value = ActiveStatus("")

        self.harness.set_leader(False)
        connection.return_value.__enter__.return_value.is_ready = True
        status_connection.return_value.__enter__.return_value.get_replset_status.return_value = {
            "1.1.1.1": "PRIMARY"
        }
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Replica set primary"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.helpers.MongoDBConnection")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_update_status_secondary(self, _, pbm_status, connection, status_connection):
        """Tests that update status identifies secondary units and doesn't update status."""
        # assume leader has already initialised the replica set
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        pbm_status.return_value = ActiveStatus("")

        self.harness.set_leader(False)
        connection.return_value.__enter__.return_value.is_ready = True
        status_connection.return_value.__enter__.return_value.get_replset_status.return_value = {
            "1.1.1.1": "SECONDARY"
        }
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Replica set secondary"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charms.mongodb.v0.helpers.MongoDBConnection")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.MongodbOperatorCharm._connect_mongodb_exporter")
    def test_update_status_additional_messages(self, _, pbm_status, connection, status_connection):
        """Tests status updates are correct for non-primary and non-secondary cases."""
        # assume leader has already initialised the replica set
        self.harness.set_leader(True)
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        pbm_status.return_value = ActiveStatus("")

        # Case 1: Unit has not been added to replica set yet
        self.harness.set_leader(False)
        connection.return_value.__enter__.return_value.is_ready = True
        status_connection.return_value.__enter__.return_value.get_replset_status.return_value = {}
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, WaitingStatus("Member being added.."))

        # Case 2: Unit is being removed from replica set
        status_connection.return_value.__enter__.return_value.get_replset_status.return_value = {
            "1.1.1.1": "REMOVED"
        }
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, WaitingStatus("Member is removing.."))

        # Case 3: Member is syncing to replica set
        for syncing_status in ["STARTUP", "STARTUP2", "ROLLBACK", "RECOVERING"]:
            status_connection.return_value.__enter__.return_value.get_replset_status.return_value = {
                "1.1.1.1": syncing_status
            }
            self.harness.charm.on.update_status.emit()
            self.assertEqual(self.harness.charm.unit.status, WaitingStatus("Member is syncing.."))

        # Case 4: Unknown status
        status_connection.return_value.__enter__.return_value.get_replset_status.return_value = {
            "1.1.1.1": "unknown"
        }
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("unknown"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_update_status_not_ready(self, connection):
        """Tests that if mongod is not running on this unit it restarts it."""
        connection.return_value.__enter__.return_value.is_ready = False
        self.harness.charm.app_peer_data["db_initialised"] = "True"

        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("Waiting for MongoDB to start")
        )

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_get_primary_current_unit_primary(self, connection):
        """Tests get primary outputs correct primary when called on a primary replica."""
        mock_event = mock.Mock()
        connection.return_value.__enter__.return_value.primary.return_value = "1.1.1.1"
        self.harness.charm._on_get_primary_action(mock_event)
        mock_event.set_results.assert_called_with({"replica-set-primary": "mongodb/0"})

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_get_primary_peer_unit_primary(self, connection):
        """Tests get primary outputs correct primary when called on a secondary replica."""
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("database-peers").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out the self unit not being primary but its peer being primary
        connection.return_value.__enter__.return_value.primary.return_value = "2.2.2.2"

        mock_event = mock.Mock()

        self.harness.charm._on_get_primary_action(mock_event)
        mock_event.set_results.assert_called_with({"replica-set-primary": "mongodb/1"})

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_primary_no_primary(self, connection):
        """Test that that the primary property can handle the case when there is no primary.

        Verifies that when there is no primary, the property _primary returns None.
        """
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("database-peers").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out no units being primary
        connection.return_value.__enter__.return_value.primary.return_value = None

        # verify no primary identified
        primary = self.harness.charm._primary
        self.assertEqual(primary, None)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_primary_failure(self, connection):
        """Tests that when getting the primary fails that no replica is reported as primary."""
        # verify that we raise the correct exception
        for exception in PYMONGO_EXCEPTIONS:
            connection.return_value.__enter__.return_value.primary.side_effect = exception
            self.assertEqual(self.harness.charm._primary, None)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.stop_after_attempt")
    def test_storage_detaching_failure_does_not_defer(self, retry_stop, connection):
        """Test that failure in removing replica does not defer the hook.

        Deferring Storage Detached hooks can result in un-predicable behavior and while it is
        technically possible to defer the event, it shouldn't be. This test verifies that no
        attempt to defer storage detached as made.
        """
        retry_stop.return_value = stop_after_attempt(1)
        exceptions = PYMONGO_EXCEPTIONS
        exceptions.append(NotReadyError)
        for exception in exceptions:
            connection.return_value.__enter__.return_value.remove_replset_member.side_effect = (
                exception
            )
            event = mock.Mock()
            self.harness.charm.on.mongodb_storage_detaching.emit(mock.Mock())
            event.defer.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._unit_ips")
    @patch("charm.MongoDBConnection")
    def test_process_unremoved_units_handles_errors(self, connection, _unit_ips):
        """Test failures in process_unremoved_units are handled and not raised."""
        connection.return_value.__enter__.return_value.get_replset_members.return_value = {
            "1.1.1.1",
            "2.2.2.2",
        }
        self.harness.charm._unit_ips = ["2.2.2.2"]

        for exception in [PYMONGO_EXCEPTIONS, NotReadyError]:
            connection.return_value.__enter__.return_value.remove_replset_member.side_effect = (
                exception
            )
            self.harness.charm.process_unremoved_units(mock.Mock())
            connection.return_value.__enter__.return_value.remove_replset_member.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConfiguration")
    @patch("charm.subprocess.run")
    def test_start_init_user_after_second_call(self, run, config):
        """Tests that the creation of the admin user is only performed once.

        Verifies that if the user is already set up, that no attempts to set it up again are
        made.
        """
        self.harness.set_leader(True)

        self.harness.charm._init_operator_user()
        self.assertEqual("operator-user-created" in self.harness.charm.app_peer_data, True)

        self.harness.charm._init_operator_user()
        run.assert_called_once()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    def test_set_password(self, pbm_status, connection):
        """Tests that a new admin password is generated and is returned to the user."""
        self.harness.set_leader(True)
        pbm_status.return_value = ActiveStatus("pbm")
        original_password = self.harness.charm.app_peer_data["operator-password"]
        action_event = mock.Mock()
        action_event.params = {}
        self.harness.charm._on_set_password(action_event)
        new_password = self.harness.charm.app_peer_data["operator-password"]

        # verify app data is updated and results are reported to user
        self.assertNotEqual(original_password, new_password)
        action_event.set_results.assert_called_with({"password": new_password})

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    def test_set_password_provided(self, pbm_status, connection):
        """Tests that a given password is set as the new mongodb password."""
        self.harness.set_leader(True)
        pbm_status.return_value = ActiveStatus("pbm")
        action_event = mock.Mock()
        action_event.params = {"password": "canonical123"}
        self.harness.charm._on_set_password(action_event)
        new_password = self.harness.charm.app_peer_data["operator-password"]

        # verify app data is updated and results are reported to user
        self.assertEqual("canonical123", new_password)
        action_event.set_results.assert_called_with({"password": "canonical123"})

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongoDBBackups._get_pbm_status")
    def test_set_password_failure(self, pbm_status, connection):
        """Tests failure to reset password does not update app data and failure is reported."""
        self.harness.set_leader(True)
        pbm_status.return_value = ActiveStatus("pbm")
        original_password = self.harness.charm.app_peer_data["operator-password"]
        action_event = mock.Mock()
        action_event.params = {}

        for exception in [PYMONGO_EXCEPTIONS, NotReadyError]:
            connection.return_value.__enter__.return_value.set_user_password.side_effect = (
                exception
            )
            self.harness.charm._on_set_password(action_event)
            current_password = self.harness.charm.app_peer_data["operator-password"]

            # verify passwords are not updated.
            self.assertEqual(current_password, original_password)
            action_event.fail.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBBackups._get_pbm_status")
    def test_set_backup_password_pbm_busy(self, pbm_status):
        """Tests changes to passwords fail when pbm is restoring/backing up."""
        self.harness.set_leader(True)
        original_password = "pass123"
        action_event = mock.Mock()

        for username in ["backup", "monitor", "operator"]:
            self.harness.charm.app_peer_data[f"{username}-password"] = original_password
            action_event.params = {"username": username}
            pbm_status.return_value = MaintenanceStatus("pbm")
            self.harness.charm._on_set_password(action_event)
            current_password = self.harness.charm.app_peer_data[f"{username}-password"]
            action_event.fail.assert_called()
            self.assertEqual(current_password, original_password)

    @patch("config.Config.ENV_VAR_PATH", "tests/unit/data/env.txt")
    def test_auth_not_enabled(self):
        self.assertEqual(self.harness.charm.auth_enabled(), False)

    @patch("config.Config.ENV_VAR_PATH", "tests/unit/data/env_auth.txt")
    def test_auth_enabled(self):
        self.assertEqual(self.harness.charm.auth_enabled(), True)

    @patch("charm.snap.SnapCache")
    def test_connect_mongodb_exporter_no_pass(
        self,
        snap_cache,
    ):
        """Verifies that mongodb exporter is not started without password."""
        mock_mongodb_snap = mock.Mock()
        mock_mongodb_snap.present = True
        mock_mongodb_snap.start = mock.Mock()
        snap_cache.return_value = {"charmed-mongodb": mock_mongodb_snap}

        self.harness.charm._connect_mongodb_exporter()
        mock_mongodb_snap.restart.assert_not_called()
