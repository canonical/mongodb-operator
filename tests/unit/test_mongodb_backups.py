# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from subprocess import CalledProcessError
from unittest import mock
from unittest.mock import patch

import tenacity
from charms.mongodb.v0.mongodb_backups import ResyncError, SetPBMConfigError
from charms.operator_libs_linux.v1 import snap
from ops.model import BlockedStatus, WaitingStatus
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

    @patch("charm.subprocess.check_output")
    def test_verify_resync_config_error(self, check_output):
        """Test _verify_resync goes into blocked state when config error occurs."""
        check_output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=42
        )

        self.harness.charm.backups._verify_resync()
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch("charm.subprocess.check_output")
    def test_verify_resync_cred_error(self, check_output):
        """Test _verify_resync goes into blocked state when credential error occurs."""
        check_output.side_effect = CalledProcessError(
            cmd="percona-backup-mongodb status", returncode=403
        )
        self.harness.charm.backups._verify_resync()
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch("charm.subprocess.check_output")
    def test_verify_resync_syncing(self, check_output):
        """Test _verify_resync goes into waiting state when syncing and raises an error."""
        check_output.return_value = b"Currently running:\n====\nResync op"

        # disable retry
        self.harness.charm.backups._get_pbm_status.retry.retry = tenacity.retry_if_not_result(
            lambda x: True
        )

        with self.assertRaises(ResyncError):
            self.harness.charm.backups._verify_resync()

        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

    def test_resync_config_options_failure(self):
        """Verifies _resync_config_options goes into blocked state when it can't start pbm."""
        mock_snap = mock.Mock()
        mock_snap.start.side_effect = snap.SnapError
        self.harness.charm.backups._resync_config_options(mock_snap)
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

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
    @patch("charm.MongoDBBackups._verify_resync")
    def test_backup_syncing(self, resync, subprocess):
        """Verifies backup is deferred if more time is needed to resync."""
        action_event = mock.Mock()
        action_event.params = {}
        resync.side_effect = ResyncError

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_create_backup_action(action_event)

        action_event.defer.assert_called()

    @patch("charm.subprocess.check_output")
    @patch("charm.MongoDBBackups._verify_resync")
    def test_backup_failed(self, resync, subprocess):
        """Verifies that when the backup fails we let the user know via event fail."""
        action_event = mock.Mock()
        action_event.params = {}

        subprocess.side_effect = [
            None,
            CalledProcessError(cmd="percona-backup-mongodb backup", returncode=42),
        ]

        self.harness.add_relation(RELATION_NAME, "s3-integrator")
        self.harness.charm.backups._on_create_backup_action(action_event)

        resync.assert_called()
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
    def test_s3_credentials_syncing(self, defer, resync, _set_config_options, snap):
        """Test charm defers when more time is needed to sync pbm."""
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
