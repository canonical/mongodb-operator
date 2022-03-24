# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from typing import List
from unittest import mock
from unittest.mock import call, mock_open, patch

import requests
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import (
    ConfigurationError,
    ConnectionFailure,
    MongodbOperatorCharm,
    OperationFailure,
    URLError,
    apt,
    subprocess,
)
from tests.unit.helpers import patch_network_get

REPO_NAME = "deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"
GPG_URL = "https://www.mongodb.org/static/pgp/server-5.0.asc"
REPO_ENTRY = (
    "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/5.0 multiverse"
)
REPO_MAP = {"deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"}

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

    @property
    def mongodb_config_args(self) -> List[str]:
        """Retrieves and parses config args."""
        with open("tests/unit/data/mongodb_config_args.txt") as f:
            config_args = f.read().splitlines()
            config_args_formatted = ["\n" if arg == "\\n" else arg for arg in config_args]

        return config_args_formatted

    @property
    def mongodb_config(self) -> str:
        """Retrieves config from file."""
        with open("tests/unit/data/mongodb_config.txt") as f:
            config = f.read()

        return config

    @patch("charm.MongodbOperatorCharm._add_repository")
    @patch("charm.MongodbOperatorCharm._install_apt_packages")
    def test_mongodb_install(self, _add, _install):
        """Test install calls correct functions."""
        self.harness.charm.on.install.emit()
        self.assertEqual(self.harness.charm.unit.status, MaintenanceStatus("installing MongoDB"))
        _install.assert_called_once()
        _add.assert_called_with(["mongodb-org"])

    @patch_network_get(private_address="1.1.1.1")
    def test_on_config_changed(self):
        """Test config change event properly writes to mongo.conf file."""
        open_mock = mock_open(read_data=self.mongodb_config)
        with patch("builtins.open", open_mock, create=True):
            self.harness.charm.on.config_changed.emit()

        # TODO change expected output based on config options,(once config options are implemented)
        open_mock.assert_called_with("/etc/mongod.conf", "w")
        open_mock.return_value.write.assert_has_calls(
            [mock.call(arg) for arg in self.mongodb_config_args]
        )

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_replica_ready", return_value=True)
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_on_start_full_successful_execution(
        self,
        is_replica,
        service_resume,
        _open_port_tcp,
        initialise_replica_set,
        is_mongod_ready,
        is_replica_ready,
    ):
        """Test operations of start event through a full execution.

        Tests the execution of start event such that there are no deferrals and the leader
        successfully sets up the replica set.
        """
        self.harness.set_leader(True)
        is_replica.side_effect = [False, True]

        self.harness.charm.on.start.emit()

        # Check if mongod is started
        service_resume.assert_called_with("mongod.service")

        # Make sure the port is opened
        _open_port_tcp.assert_called_with(27017)

        # Check if mongod is ready
        is_mongod_ready.assert_called()

        # Check if replica is ready
        is_replica_ready.assert_called()

        # Ensure we set an ActiveStatus for the charm
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        # Check that replica set is initialised with correct IP
        initialise_replica_set.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.MongodbOperatorCharm.app")
    def test_on_start_not_leader_doesnt_initialise_replica_set(
        self,
        app,
        _initialise_replica_set,
        service_resume,
        _open_port_tcp,
        initialise_replica_set,
        is_ready,
    ):
        """Tests that a non leader unit does not initialise the replica set."""
        self.harness.set_leader(False)
        self.harness.charm.on.start.emit()

        service_resume.assert_called()
        _open_port_tcp.assert_called()
        is_ready.assert_called()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        app.planned_units.assert_not_called()
        _initialise_replica_set.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_mongod_ready")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume", return_value=False)
    @patch("charm.service_running", return_value=False)
    def test_on_start_systemd_failure_leads_to_blocked_status(
        self, service_running, service_resume, _open_port_tcp, initialise_replica_set, is_ready
    ):
        """Test failures on systemd result in blocked status."""
        with self.assertLogs("charm", "ERROR") as logs:
            self.harness.charm.on.start.emit()
            service_resume.assert_called()
            self.assertIn("ERROR:charm:failed to enable mongod.service", logs.output)
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("couldn't start MongoDB"))
        _open_port_tcp.assert_not_called()
        is_ready.assert_not_called()
        initialise_replica_set.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    @patch("charm.service_resume")
    @patch("charm.service_running", return_value=True)
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("mongod_helpers.MongoDB.is_replica_set", return_value=False)
    def test_on_start_mongo_service_ready_doesnt_reenable(
        self, is_replica, _open_port_tcp, service_running, service_resume, is_ready
    ):
        """Test verifies that is MongoDB service is available that we don't re-enable it."""
        self.harness.set_leader(True)
        self.harness.charm.on.start.emit()
        service_running.assert_called()
        service_resume.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=False)
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.service_running", return_value=True)
    def test_on_start_mongod_not_ready_defer(
        self, service_running, initialise_replica_set, _open_port_tcp, is_ready
    ):
        """Test verifies that we wait to initialise replica set when mongod is not running."""
        self.harness.set_leader(True)
        self.harness.charm.on.start.emit()
        is_ready.assert_called()
        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("waiting for MongoDB to start")
        )
        initialise_replica_set.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_replica_set", return_value=True)
    @patch("mongod_helpers.MongoDB.is_replica_ready", return_value=False)
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.service_running", return_value=True)
    def test_on_start_replica_not_ready_waits(
        self,
        service_running,
        initialise_replica_set,
        _open_port_tcp,
        is_mongod_ready,
        is_replica_ready,
        is_replica_set,
    ):
        """Tests that if a replica is not ready that the charm goes into waiting."""
        self.harness.set_leader(True)
        self.harness.charm.on.start.emit()
        is_replica_ready.assert_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_replica_set", return_value=True)
    @patch("mongod_helpers.MongoDB.check_replica_status")
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.service_running", return_value=True)
    def test_on_start_cannot_check_replica_status(
        self,
        service_running,
        initialise_replica_set,
        _open_port_tcp,
        is_mongod_ready,
        check_replica_status,
        is_replica_set,
    ):
        """Tests that failure to check replica state results in waiting status."""
        self.harness.set_leader(True)

        for exception in PYMONGO_EXCEPTIONS:
            check_replica_status.side_effect = exception
            self.harness.charm.on.start.emit()
            self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_mongod_ready")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_running", return_value=True)
    def test_start_unable_to_open_tcp_moves_to_blocked(
        self, service_running, _open_port_tcp, is_ready
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
        key_values = {"private-address": "127.4.5.6"}
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", key_values)

        resulting_ips = self.harness.charm._unit_ips
        expected_ips = ["127.4.5.6", "1.1.1.1"]
        self.assertEqual(resulting_ips, expected_ips)

    @patch("charm.MongodbOperatorCharm._reconfigure")
    def test_mongodb_relation_joined_non_leader_does_nothing(self, reconfigure):
        """Test verifies that non-leader units don't reconfigure the replica set on joined."""
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.set_leader(False)
        self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)

        reconfigure.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_mongodb_relation_joined_peers_not_ready(self, single_replica, mongo_reconfigure):
        """Test that leader unit won't reconfigure the replica set until unit is ready.

        If the peer unit that is joining the replica set and doesn't have mongod running the
        leader unit must not reconfigure.
        """
        # preset values
        self.harness.set_leader(True)
        single_replica.return_value.is_mongod_ready.return_value = False

        # simulate 2nd MongoDB unit
        rel = self.harness.charm.model.get_relation("mongodb")
        key_values = {"private-address": "127.4.5.6"}
        self.harness.add_relation_unit(rel.id, "mongodb/1")
        self.harness.update_relation_data(rel.id, "mongodb/1", key_values)

        # verify that we do not reconfigure replica set
        mongo_reconfigure.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    @patch("charm.MongodbOperatorCharm._need_replica_set_reconfiguration")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    def test_mongodb_relation_joined_peer_ready(
        self, mongodb_reconfigure, need_reconfiguration, single_replica
    ):
        """Test leader unit operations when peer unit is ready to join the replica set.

        Verifies that when a new peer is ready to join the replica set hosts get updated
        accordingly and reconfigured if necessary.
        """
        # preset values
        self.harness.set_leader(True)
        single_replica.return_value.is_ready.return_value = True

        # test cases where replica set should and shouldn't be reconfigured
        for reconfiguration in [False, True]:
            self.harness.charm._need_replica_set_reconfiguration = reconfiguration

            # simulate 2nd MongoDB unit
            rel = self.harness.charm.model.get_relation("mongodb")
            key_values = {"private-address": "127.4.5.6"}
            self.harness.add_relation_unit(rel.id, "mongodb/1")
            self.harness.update_relation_data(rel.id, "mongodb/1", key_values)

            # check if mongod reconfigured replica set
            if reconfiguration:
                mongodb_reconfigure.assert_called()

                # verify replica set hosts updated accordingly
                self.assertEqual(
                    self.harness.charm._replica_set_hosts,
                    ["127.4.5.6", "1.1.1.1"],
                )

            else:
                mongodb_reconfigure.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    @patch("charm.MongodbOperatorCharm._need_replica_set_reconfiguration")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    def test_mongodb_relation_joined_failure(
        self, mongodb_reconfigure, need_reconfiguration, single_replica
    ):
        """Tests that when reconfigure operations fail we go into the Waiting Status."""
        # preset values
        self.harness.set_leader(True)
        single_replica.return_value.is_mongod_ready.return_value = True
        self.harness.charm._need_replica_set_reconfiguration = True

        # test cases where replica set should and shouldn't be reconfigured
        for exception in PYMONGO_EXCEPTIONS:
            mongodb_reconfigure.side_effect = exception

            # simulate 2nd MongoDB unit
            rel = self.harness.charm.model.get_relation("mongodb")
            key_values = {"private-address": "127.4.5.6"}
            self.harness.add_relation_unit(rel.id, "mongodb/1")
            self.harness.update_relation_data(rel.id, "mongodb/1", key_values)

            # charm waits
            self.assertEqual(
                self.harness.charm.unit.status, WaitingStatus("waiting to reconfigure replica set")
            )

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    @patch("charm.MongodbOperatorCharm._need_replica_set_reconfiguration")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    def test_mongodb_departed_reconfigures_replicas(
        self, mongodb_reconfigure, need_reconfiguration, single_replica
    ):
        """Tests that when reconfigure operations fail we go into the Waiting Status."""
        # preset values
        self.harness.set_leader(True)

        # add peer unit
        rel = self.harness.charm.model.get_relation("mongodb")
        rel_id = rel.id
        key_values = {"private-address": "127.4.5.6"}
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", key_values)

        # remove unit to trigger event
        self.harness.remove_relation_unit(rel_id, "mongodb/1")

        # verify replica set hosts updated accordingly
        self.assertEqual(
            self.harness.charm._replica_set_hosts,
            ["1.1.1.1"],
        )

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._peers")
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("charm.MongodbOperatorCharm.app")
    @patch("mongod_helpers.MongoDB.is_replica_set", return_value=False)
    def test_initialise_replica_failure_leads_to_waiting_state(
        self, is_replica, app, service_resume, _, initialise_replica_set, is_ready, peers
    ):
        """Tests that failure to initialise replica set goes into Waiting Status."""
        # set peer data so that leader doesn't reconfigure set on set_leader
        peers_data = {}
        peers_data[app] = {
            "_new_leader_must_reconfigure": "False",
        }
        peers.data = peers_data

        self.harness.set_leader(True)
        app.planned_units.return_value = 1
        log_messages = [
            "ERROR:charm:error initialising replica sets in _on_start: error: error message",
            "ERROR:charm:error initialising replica sets in _on_start: error: error message",
            "ERROR:charm:error initialising replica sets in _on_start: error: error message",
        ]
        for exception, log_message in zip(PYMONGO_EXCEPTIONS, log_messages):
            with self.assertLogs("charm", "DEBUG") as logs:
                initialise_replica_set.side_effect = exception
                self.harness.charm.on.start.emit()
                initialise_replica_set.assert_called()
                self.assertIn(log_message, logs.output)

            self.assertEqual(
                self.harness.charm.unit.status, WaitingStatus("waiting to initialise replica set")
            )

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_replica_ready", return_value=True)
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_running", return_value=True)
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_initialise_replica_success(
        self,
        is_replica,
        service_running,
        _open_port_tcp,
        initialise_replica_set,
        is_mongod_ready,
        is_replica_ready,
    ):
        """Tests successful operations of initialise replica set.

        This test checks that when successful initialisation of replica set occurs that replica
        set hosts are updated accordingly and that the unit goes into Active Status.
        """
        self.harness.set_leader(True)
        is_replica.side_effect = [False, True]

        self.harness.charm.on.start.emit()
        initialise_replica_set.assert_called()

        # assert added to replica set hosts
        self.assertEqual(
            self.harness.charm._replica_set_hosts,
            ["1.1.1.1"],
        )

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus(""))

    @patch_network_get(private_address="1.1.1.1")
    def test_single_mongo_replica(self):
        """Tests that when creating a single replica of MongoDB it has the correct ip address."""
        ip_address = "1.1.1.1"
        mongo_replica = self.harness.charm._single_mongo_replica(ip_address)
        self.assertEqual(mongo_replica._calling_unit_ip, ip_address)

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary", return_value="1.1.1.1")
    def test_update_status_primary(self, primary):
        """Tests that update status identifies the primary unit and updates status."""
        self.harness.charm.on.update_status.emit()
        primary.assert_called()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Replica set primary"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary", return_value="2.2.2.2")
    @patch("ops.model.ActiveStatus")
    def test_update_status_secondary(self, active_status, primary):
        """Tests that update status identifies secondary units and doesn't update status."""
        self.harness.charm.on.update_status.emit()
        primary.assert_called()
        active_status.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary", return_value="1.1.1.1")
    def test_get_primary_current_unit_primary(self, primary):
        """Tests get primary outputs correct primary when called on a primary replica."""
        mock_event = mock.Mock()
        self.harness.charm._on_get_primary_action(mock_event)
        mock_event.set_results.assert_called_with({"replica-set-primary": "mongodb/0"})

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary")
    def test_get_primary_peer_unit_primary(self, primary):
        """Tests get primary outputs correct primary when called on a secondary replica."""
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out the self unit not being primary but its peer being primary
        primary.return_value = "2.2.2.2"

        mock_event = mock.Mock()

        self.harness.charm._on_get_primary_action(mock_event)
        mock_event.set_results.assert_called_with({"replica-set-primary": "mongodb/1"})

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary")
    def test_primary_no_primary(self, primary_helper):
        """Test that that the primary property can handle the case when there is no primary.

        Verifies that when there is no primary, the property _primary returns None.
        """
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out no units being primary
        primary_helper.return_value = None

        # verify no primary identified
        primary = self.harness.charm._primary
        self.assertEqual(primary, None)

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary", return_value="1.1.1.1")
    def test_primary_self_primary(self, primary_helper):
        """Test that that the primary property can identify itself as primary.

        Verifies that when the calling unit is primary, the calling unit is identified as primary.
        """
        primary = self.harness.charm._primary
        self.assertEqual(primary, "mongodb/0")

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary")
    def test_primary_peer_primary(self, primary_helper):
        """Test that that the primary property can identify a peer unit as primary.

        Verifies that when a non-calling unit is primary, the non-calling unit is identified as
        primary.
        """
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out the self unit not being primary but its peer being primary
        primary_helper.return_value = "2.2.2.2"

        primary = self.harness.charm._primary
        self.assertEqual(primary, "mongodb/1")

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.primary")
    def test_primary_failure(self, primary_helper):
        """Tests that when getting the primary fails that no replica is reported as primary."""
        # verify that we raise the correct exception
        for exception in PYMONGO_EXCEPTIONS:
            primary_helper.side_effect = exception
            self.assertEqual(self.harness.charm._primary, None)

    @patch("charm.MongodbOperatorCharm._unit_ips")
    @patch("charm.MongodbOperatorCharm._replica_set_hosts")
    def test_need_replica_set_reconfiguration(self, units, hosts):
        """Tests that boolean helper _need_replica_set_reconfiguration operates as expected."""
        self.harness.charm._unit_ips = ["1.1.1.1", "2.2.2.2"]
        self.harness.charm._replica_set_hosts = ["1.1.1.1"]
        self.assertEqual(self.harness.charm._need_replica_set_reconfiguration, True)

        self.harness.charm._unit_ips = ["1.1.1.1", "2.2.2.2"]
        self.harness.charm._replica_set_hosts = ["1.1.1.1", "2.2.2.2"]
        self.assertEqual(self.harness.charm._need_replica_set_reconfiguration, False)

    @patch_network_get(private_address="1.1.1.1")
    def test_on_leader_elected_updates_relation_data(self):
        """Test that leader elected properly handles relation data.

        Verifies that when a leader gets re-elected it properly sets up the replica set hosts.
        """
        self.harness.set_leader(True)
        self.harness.charm.on.leader_elected.emit()

        # check that we reset the replica_set_hosts
        self.assertEqual(self.harness.charm._replica_set_hosts, ["1.1.1.1"])

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.remove_replica")
    @patch("mongod_helpers.MongoDB.primary_step_down")
    @patch("mongod_helpers.MongoDB.primary", return_value="1.1.1.1")
    def test_storage_detaching_primary_step_down_failure(
        self, primary, primary_step_down, remove_replica
    ):
        """Test that failure in stepping down the primary is properly handled.

        Verifies that when the primary fails to step down with an error that we don't attempt to
        reconfigure the replica set and that we go into the waiting status.
        """
        for exception in PYMONGO_EXCEPTIONS:
            primary_step_down.side_effect = exception
            self.harness.charm.on.mongodb_storage_detaching.emit(mock.Mock())
            primary_step_down.assert_called()
            remove_replica.assert_not_called()

            self.assertEqual(
                self.harness.charm.unit.status, WaitingStatus("waiting to reconfigure replica set")
            )

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.remove_replica")
    @patch("mongod_helpers.MongoDB.primary_step_down")
    def test_storage_detaching_replica_removal_failure(self, _, remove_replica):
        """Test that failure in removing unit is properly handled.

        Verifies that when a replica fails to get removed that we go into the waiting status.
        """
        for exception in PYMONGO_EXCEPTIONS:
            remove_replica.side_effect = exception
            self.harness.charm.on.mongodb_storage_detaching.emit(mock.Mock())
            remove_replica.assert_called()

            self.assertEqual(
                self.harness.charm.unit.status, WaitingStatus("waiting to reconfigure replica set")
            )
