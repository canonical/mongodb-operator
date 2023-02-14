# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from subprocess import CalledProcessError
from unittest import mock
from unittest.mock import patch

import tenacity
from charms.mongodb.v0.mongodb_backups import (
    PBMBusyError,
    ResyncError,
    SetPBMConfigError,
    stop_after_attempt,
    wait_fixed,
)
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import MongodbOperatorCharm
from tests.unit.helpers import patch_network_get

RELATION_NAME = "s3-credentials"


class TestMongoBackups(unittest.TestCase):
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self):
        self.harness = Harness(MongodbOperatorCharm)
        self.harness.begin()
        self.harness.add_relation("database-peers", "database-peers")
        self.harness.set_leader(True)
        self.charm = self.harness.charm
        self.addCleanup(self.harness.cleanup)

    def test_current_pbm_op(self):
        """Test if _current_pbm_op can identify the operation pbm is running."""
        action = self.harness.charm.backups._current_pbm_op(
            "nothing\nCurrently running:\n====\nexpected action"
        )
        self.assertEqual(action, "expected action")

        no_action = self.harness.charm.backups._current_pbm_op("pbm not started")
        self.assertEqual(no_action, "")

    @patch("charm.snap.SnapCache")
    def test_get_pbm_status_snap_not_present(self, snap):
        """Tests that when the snap is not present pbm is in blocked state."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = False
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        self.assertTrue(isinstance(self.harness.charm.backups._get_pbm_status(), BlockedStatus))

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_get_pbm_status_resync(self, snap, output):
        """Tests that when pbm is resyncing that pbm is in waiting state."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        output.return_value = b"Currently running:\n====\nResync op"
        self.assertTrue(isinstance(self.harness.charm.backups._get_pbm_status(), WaitingStatus))

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_get_pbm_status_running(self, snap, output):
        """Tests that when pbm not running an op that pbm is in active state."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        output.return_value = b"Currently running:\n====\n(none)"
        self.assertTrue(isinstance(self.harness.charm.backups._get_pbm_status(), ActiveStatus))

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_get_pbm_status_backup(self, snap, output):
        """Tests that when pbm running a backup that pbm is in maintenance state."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        output.return_value = b"Currently running:\n====\nSnapshot backup"
        self.assertTrue(
            isinstance(self.harness.charm.backups._get_pbm_status(), MaintenanceStatus)
        )

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_get_pbm_status_incorrect_cred(self, snap, output):
        """Tests that when pbm has incorrect credentials that pbm is in blocked state."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=403, output=b"status code: 403"
        )
        self.assertTrue(isinstance(self.harness.charm.backups._get_pbm_status(), BlockedStatus))

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_get_pbm_status_incorrect_conf(self, snap, output):
        """Tests that when pbm has incorrect configs that pbm is in blocked state."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=42, output=b""
        )
        self.assertTrue(isinstance(self.harness.charm.backups._get_pbm_status(), BlockedStatus))

    @patch("charm.subprocess.check_output")
    def test_verify_resync_config_error(self, check_output):
        """Tests that when pbm cannot resync due to configs that it raises an error."""
        mock_snap = mock.Mock()
        check_output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=42
        )

        with self.assertRaises(CalledProcessError):
            self.harness.charm.backups._resync_config_options(mock_snap)

    @patch("charm.subprocess.check_output")
    def test_verify_resync_cred_error(self, check_output):
        """Tests that when pbm cannot resync due to creds that it raises an error."""
        mock_snap = mock.Mock()
        check_output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=403, output=b"status code: 403"
        )
        with self.assertRaises(CalledProcessError):
            self.harness.charm.backups._resync_config_options(mock_snap)

    @patch("charm.subprocess.check_output")
    def test_verify_resync_syncing(self, check_output):
        """Tests that when pbm needs more time to resync that it raises an error."""
        mock_snap = mock.Mock()
        check_output.return_value = b"Currently running:\n====\nResync op"

        # disable retry
        self.harness.charm.backups._wait_pbm_status.retry.retry = tenacity.retry_if_not_result(
            lambda x: True
        )

        with self.assertRaises(ResyncError):
            self.harness.charm.backups._resync_config_options(mock_snap)

    @patch("charms.mongodb.v0.mongodb_backups.wait_fixed")
    @patch("charms.mongodb.v0.mongodb_backups.stop_after_attempt")
    @patch("charm.MongoDBBackups._get_pbm_status")
    def test_resync_config_options_failure(self, pbm_status, retry_stop, retry_wait):
        """Verifies _resync_config_options raises an error when a resync cannot be performed."""
        retry_stop.return_value = stop_after_attempt(1)
        retry_stop.return_value = wait_fixed(1)
        pbm_status.return_value = WaitingStatus()
        mock_snap = mock.Mock()
        with self.assertRaises(PBMBusyError):
            self.harness.charm.backups._resync_config_options(mock_snap)

        pbm_status.return_value = MaintenanceStatus()
        mock_snap = mock.Mock()
        with self.assertRaises(PBMBusyError):
            self.harness.charm.backups._resync_config_options(mock_snap)

    @patch("charm.subprocess.check_output")
    def test_set_config_options(self, check_output):
        """Verifies _set_config_options failure raises SetPBMConfigError."""
        check_output.side_effect = (
            CalledProcessError(
                cmd="percona-backup-mongodb config --set this_key=doesnt_exist", returncode=42
            ),
        )
        with self.assertRaises(SetPBMConfigError):
            self.harness.charm.backups._set_config_options({"this_key": "doesnt_exist"})

    def test_backup_without_rel(self):
        """Verifies no backups are attempted without s3 relation."""
        action_event = mock.Mock()
        action_event.params = {}

        self.harness.charm.backups._on_create_backup_action(action_event)
        action_event.fail.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_backup_syncing(self, snap, output):
        """Verifies backup is deferred if more time is needed to resync."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        action_event = mock.Mock()
        action_event.params = {}
        output.return_value = b"Currently running:\n====\nResync op"

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_create_backup_action(action_event)

        action_event.defer.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_backup_running_backup(self, snap, output):
        """Verifies backup is fails if another backup is already running."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        action_event = mock.Mock()
        action_event.params = {}
        output.return_value = b"Currently running:\n====\nSnapshot backup"

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_create_backup_action(action_event)

        action_event.fail.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_backup_wrong_cred(self, snap, output):
        """Verifies backup is fails if the credentials are incorrect."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        action_event = mock.Mock()
        action_event.params = {}
        output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=403, output=b"status code: 403"
        )

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_create_backup_action(action_event)
        action_event.fail.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.snap.SnapCache")
    def test_backup_failed(self, snap, pbm_status, output):
        """Verifies backup is fails if the pbm command failed."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        action_event = mock.Mock()
        action_event.params = {}
        pbm_status.return_value = ActiveStatus("")

        output.side_effect = CalledProcessError(cmd="percona-backup-mongodb backup", returncode=42)

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_create_backup_action(action_event)

        action_event.fail.assert_called()

    def test_backup_list_without_rel(self):
        """Verifies no backup lists are attempted without s3 relation."""
        action_event = mock.Mock()
        action_event.params = {}

        self.harness.charm.backups._on_list_backups_action(action_event)
        action_event.fail.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_backup_list_syncing(self, snap, output):
        """Verifies backup list is deferred if more time is needed to resync."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        action_event = mock.Mock()
        action_event.params = {}
        output.return_value = b"Currently running:\n====\nResync op"

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_list_backups_action(action_event)

        action_event.defer.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.snap.SnapCache")
    def test_backup_list_wrong_cred(self, snap, output):
        """Verifies backup list fails with wrong credentials."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        action_event = mock.Mock()
        action_event.params = {}
        output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=403, output=b"status code: 403"
        )

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_list_backups_action(action_event)
        action_event.fail.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.MongoDBBackups._get_pbm_status")
    @patch("charm.snap.SnapCache")
    def test_backup_list_failed(self, snap, pbm_status, output):
        """Verifies backup list fails if the pbm command fails."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}

        action_event = mock.Mock()
        action_event.params = {}
        pbm_status.return_value = ActiveStatus("")

        output.side_effect = CalledProcessError(cmd="percona-backup-mongodb list", returncode=42)

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_list_backups_action(action_event)

        action_event.fail.assert_called()

    @patch("ops.framework.EventBase.defer")
    def test_s3_credentials_no_db(self, defer):
        """Verifies that when there is no DB that setting credentials is deferred."""
        del self.harness.charm.app_peer_data["db_initialised"]

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        defer.assert_called()

    @patch("ops.framework.EventBase.defer")
    @patch("charm.snap.SnapCache")
    def test_s3_credentials_no_snap(self, snap, defer):
        """Verifies that when there is no DB that setting credentials is deferred."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = False
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        self.harness.charm.app_peer_data["db_initialised"] = "True"

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        defer.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.snap.SnapCache")
    @patch("charm.MongoDBBackups._set_config_options")
    def test_s3_credentials_set_pbm_failure(self, _set_config_options, snap):
        """Test charm goes into blocked state when setting pbm configs fail."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        mock_pbm_snap.set = mock.Mock()
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        _set_config_options.side_effect = SetPBMConfigError
        self.harness.charm.app_peer_data["db_initialised"] = "True"

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.snap.SnapCache")
    @patch("charm.MongoDBBackups._set_config_options")
    @patch("charm.MongoDBBackups._resync_config_options")
    @patch("ops.framework.EventBase.defer")
    def test_s3_credentials_config_error(self, defer, resync, _set_config_options, snap):
        """Test charm defers when more time is needed to sync pbm."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        mock_pbm_snap.set = mock.Mock()
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        resync.side_effect = SetPBMConfigError

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.snap.SnapCache")
    @patch("charm.MongoDBBackups._set_config_options")
    @patch("charm.MongoDBBackups._resync_config_options")
    @patch("ops.framework.EventBase.defer")
    def test_s3_credentials_syncing(self, defer, resync, _set_config_options, snap):
        """Test charm defers when more time is needed to sync pbm credentials."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        mock_pbm_snap.set = mock.Mock()
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        resync.side_effect = ResyncError

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        defer.assert_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.snap.SnapCache")
    @patch("charm.MongoDBBackups._set_config_options")
    @patch("charm.MongoDBBackups._resync_config_options")
    @patch("ops.framework.EventBase.defer")
    def test_s3_credentials_pbm_busy(self, defer, resync, _set_config_options, snap):
        """Test charm defers when more time is needed to sync pbm."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        mock_pbm_snap.set = mock.Mock()
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        resync.side_effect = PBMBusyError

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        defer.assert_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.snap.SnapCache")
    @patch("charm.MongoDBBackups._set_config_options")
    @patch("charm.MongoDBBackups._resync_config_options")
    @patch("ops.framework.EventBase.defer")
    def test_s3_credentials_snap_start_error(self, defer, resync, _set_config_options, snap):
        """Test charm defers when more time is needed to sync pbm."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        mock_pbm_snap.set = mock.Mock()
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        resync.side_effect = snap.SnapError

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        defer.assert_not_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.snap.SnapCache")
    @patch("charm.MongoDBBackups._set_config_options")
    @patch("charm.MongoDBBackups._resync_config_options")
    @patch("ops.framework.EventBase.defer")
    @patch("charm.subprocess.check_output")
    def test_s3_credentials_pbm_error(self, output, defer, resync, _set_config_options, snap):
        """Test charm defers when more time is needed to sync pbm."""
        mock_pbm_snap = mock.Mock()
        mock_pbm_snap.present = True
        mock_pbm_snap.set = mock.Mock()
        snap.return_value = {"percona-backup-mongodb": mock_pbm_snap}
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        resync.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=403, output=b"status code: 403"
        )
        output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=403, output=b"status code: 403"
        )

        # triggering s3 event with correct fields
        mock_s3_info = mock.Mock()
        mock_s3_info.return_value = {"access-key": "noneya", "secret-key": "business"}
        self.harness.charm.backups.s3_client.get_s3_connection_info = mock_s3_info
        relation_id = self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.add_relation_unit(relation_id, "s3-integrator/0")
        self.harness.update_relation_data(
            relation_id,
            "s3-integrator/0",
            {"bucket": "hat"},
        )

        defer.assert_not_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    def test_parse_backup(self):
        """Checks that parsing backups from `pbm list` produces the correct output."""
        backup_id, backup_type, backup_status = self.harness.charm.backups._parse_backup(
            "2023-02-08T15:19:34Z <logical> [restore_to_time: 2023-02-08T15:19:39Z]"
        )
        self.assertEqual(backup_id, "2023-02-08T15:19:34Z")
        self.assertEqual(backup_type, "logical")
        self.assertEqual(backup_status, "finished")

    def test_line_contains_backup(self):
        """Test helper that returns a bool if a backup is present."""
        # Case 1: backup is present
        contains_backup = self.harness.charm.backups._line_contains_backup(
            "2023-02-08T15:19:34Z <logical> [restore_to_time: 2023-02-08T15:19:39Z]"
        )
        self.assertEqual(contains_backup, True)

        # Case 2: no backup is present
        contains_backup = self.harness.charm.backups._line_contains_backup("Pbm status summary:")
        self.assertEqual(contains_backup, False)

    @patch("charm.subprocess.check_output")
    def test_get_inprogress_backups(self, check_output):
        """Tests in progress backups are correctly reported."""
        # Case 1: no backup is occurring
        check_output.return_value = b"Snapshot backup:\n====\nResync op"
        inprogress_backups = self.harness.charm.backups._get_inprogress_backups()
        self.assertEqual(inprogress_backups, [])

        # Case 2: a backup is occurring
        check_output.return_value = b'Currently running:\n====\nSnapshot backup "2023-02-14T13:58:27Z", started at 2023-02-14T13:58:27Z. Status: snapshot backup. [op id: 63eb93834febe519118a501c]'
        inprogress_backups = self.harness.charm.backups._get_inprogress_backups()
        self.assertEqual(inprogress_backups, [("2023-02-14T13:58:27Z", "logical", "in progress")])

    @patch("charm.subprocess.check_output")
    def test_get_failed_backups(self, check_output):
        """Tests that failed backups are correctly identified."""
        # Case 1: `pbm status` only shows successful backups
        check_output.return_value = b"Backups:\n====\n2023-02-08T15:19:34Z <logical> [restore_to_time: 2023-02-08T15:19:39Z]"
        failed_backups = self.harness.charm.backups._get_failed_backups()
        assert failed_backups == []

        # Case 2: `pbm status` shows failed backup
        check_output.return_value = b"Backups:\n====\n2023-02-14T13:54:48Z 0.00B <logical> [ERROR: get file 2023-02-14T13:54:48Z/mongodb/metadata.json: no such file] [2023-02-14T13:58:28Z]"
        failed_backups = self.harness.charm.backups._get_failed_backups()
        backup_id, backup_type, backup_status = failed_backups[0]
        self.assertEqual(backup_id, "2023-02-14T13:54:48Z")
        self.assertEqual(backup_type, "logical")
        self.assertEqual(backup_status, "failed")

    @patch("charm.MongoDBBackups._get_inprogress_backups")
    @patch("charm.MongoDBBackups._get_failed_backups")
    def test_generate_backup_list_output(self, failed_backups, inprogress_backups):
        """Tests correct formation of backup list output.

        Specifically the spacing of the backups, the header, the backup order, and the backup
        contents.
        """
        successful_backups = "Backup snapshots:\n1990-02-08T15:19:34Z <physical> [restore_to_time: 2023-02-08T15:19:39Z]"
        failed_backups.return_value = [("2000-02-14T13:54:48Z", "logical", "failed")]
        inprogress_backups.return_value = [("2001-02-14T13:58:27Z", "logical", "in progress")]

        formatted_output = self.harness.charm.backups._generate_backup_list_output(
            successful_backups
        )
        formatted_output = formatted_output.split("\n")
        header = formatted_output[0]
        self.assertEqual(header, "backup-id             | backup-type  | backup-status")
        divider = formatted_output[1]
        self.assertEqual(
            divider, "-" * len("backup-id             | backup-type  | backup-status")
        )
        eariest_backup = formatted_output[2]
        self.assertEqual(eariest_backup, "1990-02-08T15:19:34Z  | physical     | finished")
        failed_backup = formatted_output[3]
        self.assertEqual(failed_backup, "2000-02-14T13:54:48Z  | logical      | failed")
        inprogress_backup = formatted_output[4]
        self.assertEqual(inprogress_backup, "2001-02-14T13:58:27Z  | logical      | in progress")
