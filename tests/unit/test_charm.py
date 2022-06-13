# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest import mock
from unittest.mock import call, patch

import requests
from charms.operator_libs_linux.v1 import systemd
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness
from pymongo.errors import ConfigurationError, ConnectionFailure, OperationFailure

from charm import MongodbOperatorCharm, NotReadyError, URLError, apt, subprocess
from tests.unit.helpers import patch_network_get

REPO_NAME = "deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"
GPG_URL = "https://www.mongodb.org/static/pgp/server-5.0.asc"
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


class TestCharm(unittest.TestCase):
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_rel_id = self.harness.add_relation("mongodb", "mongodb")

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_admin_user")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.systemd.service_start")
    @patch("charm.Path")
    @patch("builtins.open")
    @patch("charm.os")
    @patch("charm.pwd")
    def test_on_start_not_leader_doesnt_initialise_replica_set(
        self, pwd, os, open, path, service_start, _open_port_tcp, init_admin, connection
    ):
        """Tests that a non leader unit does not initialise the replica set."""
        # Only leader can set RelationData
        self.harness.set_leader(True)
        self.harness.charm.app_data["keyfile"] = "/etc/mongodb/keyFile"

        self.harness.set_leader(False)
        self.harness.charm.on.start.emit()

        service_start.assert_called()
        _open_port_tcp.assert_called()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        connection.return_value.__enter__.return_value.init_replset.assert_not_called()
        init_admin.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_admin_user")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.systemd.service_start", side_effect=systemd.SystemdError)
    @patch("charm.systemd.service_running", return_value=False)
    @patch("charm.Path")
    @patch("builtins.open")
    @patch("charm.os")
    @patch("charm.pwd")
    def test_on_start_systemd_failure_leads_to_blocked_status(
        self,
        pwd,
        os,
        open,
        path,
        service_running,
        service_start,
        _open_port_tcp,
        init_admin,
        connection,
    ):
        """Test failures on systemd result in blocked status."""
        self.harness.set_leader(True)
        self.harness.charm.on.start.emit()
        service_start.assert_called()

        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))
        _open_port_tcp.assert_not_called()

        connection.return_value.__enter__.return_value.init_replset.assert_not_called()
        init_admin.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.systemd.service_start")
    @patch("charm.systemd.service_running", return_value=True)
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.Path")
    @patch("builtins.open")
    @patch("charm.os")
    @patch("charm.pwd")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_admin_user")
    def test_on_start_mongo_service_ready_doesnt_reenable(
        self,
        init_admin,
        connection,
        pwd,
        os,
        open,
        path,
        _open_port_tcp,
        service_running,
        service_start,
    ):
        """Test verifies that is MongoDB service is available that we don't re-enable it."""
        self.harness.set_leader(True)
        self.harness.charm.on.start.emit()
        service_running.assert_called()
        service_start.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.systemd.service_running", return_value=True)
    @patch("charm.Path")
    @patch("builtins.open")
    @patch("charm.os")
    @patch("charm.pwd")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_admin_user")
    def test_on_start_mongod_not_ready_defer(
        self,
        init_admin,
        connection,
        pwd,
        os,
        open,
        path,
        service_running,
        initialise_replica_set,
        _open_port_tcp,
    ):
        """Test verifies that we wait to initialise replica set when mongod is not running."""
        self.harness.set_leader(True)
        connection.return_value.__enter__.return_value.is_ready = False

        self.harness.charm.on.start.emit()
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))
        connection.return_value.__enter__.return_value.init_replset.assert_not_called()
        init_admin.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.systemd.service_running", return_value=True)
    @patch("charm.Path")
    @patch("builtins.open")
    @patch("charm.os")
    @patch("charm.pwd")
    def test_start_unable_to_open_tcp_moves_to_blocked(
        self, pwd, os, open, path, service_running, _open_port_tcp
    ):
        """Test verifies that if TCP port cannot be opened we go to the blocked state."""
        self.harness.set_leader(True)
        _open_port_tcp.side_effect = subprocess.CalledProcessError(
            cmd="open-port 27017/TCP", returncode=1
        )
        self.harness.charm.on.start.emit()

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("failed to open TCP port for MongoDB")
        )

    @patch("charm.check_call")
    def test_set_port(self, _call):
        """Test verifies operation of set port."""
        self.harness.charm._open_port_tcp(27017)
        # Make sure the port is opened and the service is started
        self.assertEqual(_call.call_args_list, [call(["open-port", "27017/TCP"])])

    @patch("charm.check_call")
    def test_set_port_failure(self, _call):
        """Test verifies that we raise the correct errors when we fail to open a port."""
        _call.side_effect = subprocess.CalledProcessError(cmd="open-port 27017/TCP", returncode=1)

        with self.assertRaises(subprocess.CalledProcessError):
            with self.assertLogs("charm", "ERROR") as logs:
                self.harness.charm._open_port_tcp(27017)
                self.assertIn("failed opening port 27017", "".join(logs.output))

    @patch("charm.apt.add_package")
    @patch("charm.apt.update")
    def test_install_apt_packages_sucess(self, update, add_package):
        """Test verifies the correct functions get called when installing apt packages."""
        self.harness.charm._install_apt_packages(["test-package"])
        update.assert_called()
        add_package.assert_called_with(["test-package"])

    @patch("charm.apt.add_package")
    @patch("charm.apt.update")
    def test_install_apt_packages_update_failure(self, update, add_package):
        """Test verifies handling of apt update failure."""
        update.side_effect = subprocess.CalledProcessError(cmd="apt-get update", returncode=1)
        with self.assertLogs("charm", "ERROR") as logs:
            self.harness.charm._install_apt_packages(["test-package"])
            self.assertIn("failed to update apt cache: ", "".join(logs.output))
            self.assertEqual(
                self.harness.charm.unit.status, BlockedStatus("couldn't install MongoDB")
            )

    @patch("charm.apt.add_package")
    @patch("charm.apt.update")
    def test_install_apt_packages_add_package_failure(self, update, add_package):
        """Test verifies handling of apt add failure."""
        exceptions = [apt.PackageNotFoundError(), TypeError("package format incorrect")]
        log_messages = [
            "ERROR:charm:a specified package not found in package cache or on system",
            "ERROR:charm:could not add package(s) to install: package format incorrect",
        ]

        for exception, log_message in zip(exceptions, log_messages):
            with self.assertLogs("charm", "ERROR") as logs:
                add_package.side_effect = exception
                self.harness.charm._install_apt_packages(["test-package"])
                self.assertIn(log_message, logs.output)

            self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch("charm.apt.RepositoryMapping", return_value=set())
    @patch("charm.apt.DebianRepository.from_repo_line")
    @patch("charm.apt.DebianRepository.import_key")
    def test_add_repository_success(self, import_key, from_repo_line, repo_map):
        """Test operations of add repository though a full execution.

        Tests the execution of add repository such that there are no exceptions through, ensuring
        that the repository is properly added.
        """
        # preset values
        req = requests.get(GPG_URL)
        mongodb_public_key = req.text

        # verify we add the MongoDB repository
        repos = self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)
        from_repo_line.assert_called()
        (from_repo_line.return_value.import_key).assert_called_with(mongodb_public_key)
        self.assertEqual(repos, {from_repo_line.return_value})

    @patch("charm.apt.RepositoryMapping", return_value=set())
    @patch("charm.apt.DebianRepository.from_repo_line")
    @patch("charm.urlopen")
    def test_add_repository_gpg_fail_leads_to_blocked(self, urlopen, from_repo_line, repo_map):
        """Test verifies that issues with GPG key lead to a blocked state."""
        # preset values
        urlopen.side_effect = URLError("urlopen error")
        self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)

        # verify we don't add repo when an exception occurs and that we enter blocked state
        self.assertEqual(repo_map.return_value, set())
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    def test_add_repository_cant_create_list_file_blocks(self, from_repo_line, repo_map):
        """Test verifies that issues with creating list file lead to a blocked state."""
        exceptions = [
            apt.InvalidSourceError("invalid source message"),
            ValueError("value message"),
        ]
        exceptions_types = [apt.InvalidSourceError, ValueError]

        for exception_type, exception in zip(exceptions_types, exceptions):
            # verify an exception is raised when repo line fails
            with self.assertRaises(exception_type):
                from_repo_line.side_effect = exception
                self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    def test_add_repository_cant_import_key_blocks(self, from_repo_line, repo_map):
        """Test verifies that issues with importing GPG key lead to a blocked state."""
        # verify an exception is raised when we cannot import GPG key
        with self.assertRaises(apt.GPGKeyError):
            (from_repo_line.return_value.import_key).side_effect = apt.GPGKeyError(
                "import key error"
            )
            self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)

    @patch("charm.apt.RepositoryMapping", return_value=REPO_MAP)
    @patch("charm.apt.DebianRepository.from_repo_line")
    def test_add_repository_already_added(self, from_repo_line, repo_map):
        """Test verifies that if a repo is already added that the installed repos don't change."""
        # verify we don't change the repos if we already have the repo of interest
        repos = self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)
        self.assertEqual(repos, REPO_MAP)

    @patch_network_get(private_address="1.1.1.1")
    def test_unit_ips(self):
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", PEER_ADDR)

        resulting_ips = self.harness.charm._unit_ips
        expected_ips = ["127.4.5.6", "1.1.1.1"]
        self.assertEqual(resulting_ips, expected_ips)

    @patch("charm.MongoDBConnection")
    def test_mongodb_relation_joined_non_leader_does_nothing(self, connection):
        """Test verifies that non-leader units don't reconfigure the replica set on joined."""
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.set_leader(False)
        self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)
        connection.return_value.__enter__.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_mongodb_relation_joined_all_replicas_not_ready(
        self, connection
    ):
        """Tests that we go into waiting when current ReplicaSet hosts are not ready.

        Tests the scenario that if current replica set hosts are not ready, the leader goes into
        WaitingStatus and no attempt to reconfigure is made.
        """
        # preset values
        self.harness.set_leader(True)
        connection.return_value.__enter__.return_value.is_ready = False
        connection.return_value.__enter__.return_value.get_replset_members.return_value = {
            "1.1.1.1"
        }

        # simulate 2nd MongoDB unit
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.add_relation_unit(rel.id, "mongodb/1")
        self.harness.update_relation_data(rel.id, "mongodb/1", PEER_ADDR)

        # verify we go into waiting and don't reconfigure
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))
        connection.return_value.__enter__.return_value.add_replset_member.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("ops.framework.EventBase.defer")
    @patch("charm.MongoDBConnection")
    @patch("lib.charms.mongodb_libs.v0.mongodb.MongoClient")
    def test_relation_joined_get_members_failure(self, client, connection, defer):
        """Tests reconfigure does not execute when unable to get the replica set members.

        Verifies in case of relation_joined and relation departed, that when the the database
        cannot retrieve the replica set members that no attempts to remove/add units are made and
        that the the event is deferred.
        """
        # presets
        self.harness.set_leader(True)
        self.harness.charm.app_data["db_initialised"] = "True"
        rel = self.harness.charm.model.get_relation("mongodb")

        for exception in PYMONGO_EXCEPTIONS:
            connection.return_value.__enter__.return_value.get_replset_members.side_effect = exception

            # test both relation events
            for departed in [False, True]:
                if departed:
                    # simulate removing 2nd MongoDB unit
                    self.harness.remove_relation_unit(rel.id, "mongodb/1")
                else:
                    # simulate 2nd MongoDB unit joining
                    self.harness.add_relation_unit(rel.id, "mongodb/1")
                    self.harness.update_relation_data(rel.id, "mongodb/1", PEER_ADDR)

                if departed:
                    connection.return_value.__enter__.return_value.add_replset_member.assert_not_called()
                else:
                    connection.return_value.__enter__.return_value.remove_replset_member.assert_not_called()

                defer.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("ops.framework.EventBase.defer")
    @patch("charm.MongoDBConnection")
    def test_reconfigure_add_member_failure(self, connection, defer):
        """Tests reconfigure does not proceed when unable to add a member.

        Verifies in relation joined events, that when the database cannot add a member that the
        event is deferred.
        """
        # presets
        self.harness.set_leader(True)
        connection.return_value.__enter__.return_value.get_replset_members.return_value = {
            "1.1.1.1"
        }
        rel = self.harness.charm.model.get_relation("mongodb")

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
    @patch("charm.systemd.service_start")
    @patch("charm.Path")
    @patch("builtins.open")
    @patch("charm.os")
    @patch("charm.pwd")
    @patch("charm.MongoDBConnection")
    @patch("charm.MongodbOperatorCharm._init_admin_user")
    def test_initialise_replica_failure_leads_to_waiting_state(
        self,
        init_admin,
        connection,
        pwd,
        os,
        open,
        path,
        service_start,
        _,
    ):
        """Tests that failure to initialise replica set goes into Waiting Status."""
        # set peer data so that leader doesn't reconfigure set on set_leader

        self.harness.set_leader(True)
        self.harness.charm.app_data["_new_leader_must_reconfigure"] = "False"
        connection.return_value.__enter__.return_value.is_ready = True

        for exception in PYMONGO_EXCEPTIONS:
            connection.return_value.__enter__.return_value.init_replset.side_effect = exception
            self.harness.charm.on.start.emit()
            connection.return_value.__enter__.return_value.init_replset.assert_called()
            init_admin.assert_not_called()
            self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    def test_update_status_primary(self, connection):
        """Tests that update status identifies the primary unit and updates status."""
        connection.return_value.__enter__.return_value.primary.return_value = "1.1.1.1"
        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Replica set primary"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBConnection")
    @patch("ops.model.ActiveStatus")
    def test_update_status_secondary(self, active_status, connection):
        """Tests that update status identifies secondary units and doesn't update status."""
        connection.return_value.__enter__.return_value.primary.return_value = "2.2.2.2"
        self.harness.charm.on.update_status.emit()
        active_status.assert_not_called()

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
        rel_id = self.harness.charm.model.get_relation("mongodb").id
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
        rel_id = self.harness.charm.model.get_relation("mongodb").id
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
    def test_storage_detaching_failure_does_not_defer(self, connection):
        """Test that failure in removing replica does not defer the hook.

        Deferring Storage Detached hooks can result in un-predicable behavior and while it is
        technically possible to defer the event, it shouldn't be. This test verifies that no
        attempt to defer storage detached as made.
        """
        for exception in [PYMONGO_EXCEPTIONS, NotReadyError]:
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
            "1.1.1.1", "2.2.2.2"}
        self.harness.charm._unit_ips = ["2.2.2.2"]

        for exception in [PYMONGO_EXCEPTIONS, NotReadyError]:
            connection.return_value.__enter__.return_value.remove_replset_member.side_effect = (
                exception
            )
            self.harness.charm.process_unremoved_units(mock.Mock())
            connection.return_value.__enter__.return_value.remove_replset_member.assert_called()
