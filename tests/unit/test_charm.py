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


class TestCharm(unittest.TestCase):
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_rel_id = self.harness.add_relation("mongodb", "mongodb")

    @property
    def mongodb_config_args(self) -> List[str]:
        with open("tests/unit/data/mongodb_config_args.txt") as f:
            config_args = f.read().splitlines()
            config_args_formatted = ["\n" if arg == "\\n" else arg for arg in config_args]

        return config_args_formatted

    @property
    def mongodb_config(self) -> str:
        with open("tests/unit/data/mongodb_config.txt") as f:
            config = f.read()

        return config

    @patch("charm.MongodbOperatorCharm._add_repository")
    @patch("charm.MongodbOperatorCharm._install_apt_packages")
    def test_mongodb_install(self, _add, _install):
        self.harness.charm.on.install.emit()
        self.assertEqual(self.harness.charm.unit.status, MaintenanceStatus("installing MongoDB"))
        _install.assert_called_once()
        _add.assert_called_with(["mongodb-org"])

    @patch_network_get(private_address="1.1.1.1")
    def test_on_config_changed(self):

        open_mock = mock_open(read_data=self.mongodb_config)
        with patch("builtins.open", open_mock, create=True):
            self.harness.charm.on.config_changed.emit()

        # TODO change expected output based on config options,(once config options are implemented)
        open_mock.assert_called_with("/etc/mongod.conf", "w")
        open_mock.return_value.write.assert_has_calls(
            [mock.call(arg) for arg in self.mongodb_config_args]
        )

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_on_start_full_successful_execution(
        self, is_replica, service_resume, _open_port_tcp, initialise_replica_set, is_ready
    ):
        self.harness.set_leader(True)
        is_ready.return_value = True
        is_replica.side_effect = [False, True]

        self.harness.charm.on.start.emit()

        # Check if mongod is started
        service_resume.assert_called_with("mongod.service")

        # Make sure the port is opened
        _open_port_tcp.assert_called_with(27017)

        # Check if mongod is ready
        is_ready.assert_called()

        # Ensure we set an ActiveStatus for the charm
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        # Check that replica set is initialised with correct IP
        initialise_replica_set.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
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
        self.harness.set_leader(False)
        is_ready.return_value = True
        self.harness.charm.on.start.emit()

        service_resume.assert_called()
        _open_port_tcp.assert_called()
        is_ready.assert_called_with(standalone=True)
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
        app.planned_units.assert_not_called()
        _initialise_replica_set.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("charm.service_running")
    def test_on_start_systemd_failure_leads_to_blocked_status(
        self, service_running, service_resume, _open_port_tcp, initialise_replica_set, is_ready
    ):
        service_running.return_value = False
        service_resume.return_value = False

        with self.assertLogs("charm", "ERROR") as logs:
            self.harness.charm.on.start.emit()
            service_resume.assert_called()
            self.assertIn("ERROR:charm:failed to enable mongod.service", logs.output)
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("couldn't start MongoDB"))
        _open_port_tcp.assert_not_called()
        is_ready.assert_not_called()
        initialise_replica_set.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("charm.service_resume")
    @patch("charm.service_running")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_on_start_mongo_service_ready_doesnt_reenable(
        self, is_replica, _open_port_tcp, service_running, service_resume, is_ready
    ):
        is_replica.return_value = False
        self.harness.set_leader(True)
        service_running.return_value = True
        is_ready.return_value = True
        self.harness.charm.on.start.emit()
        service_running.assert_called()
        service_resume.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("charm.service_running")
    def test_on_start_not_ready_defer(
        self, service_running, initialise_replica_set, _open_port_tcp, is_ready
    ):
        self.harness.set_leader(True)
        service_running.return_value = True
        is_ready.return_value = False
        self.harness.charm.on.start.emit()
        is_ready.assert_called()
        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("waiting for MongoDB to start")
        )
        initialise_replica_set.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("charm.service_running")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_on_start_mongo_service_running_doesnt_resume_service(
        self,
        is_replica,
        service_running,
        service_resume,
        _open_port_tcp,
        initialise_replica_set,
        is_ready,
    ):
        self.harness.set_leader(True)
        service_running.return_value = True
        is_replica.return_value = False
        self.harness.charm.on.start.emit()

        service_resume.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_running")
    def test_start_unable_to_open_tcp_moves_to_blocked(
        self, service_running, _open_port_tcp, is_ready
    ):
        self.harness.set_leader(True)
        service_running.return_value = True
        _open_port_tcp.side_effect = subprocess.CalledProcessError(
            cmd="open-port 27017/TCP", returncode=1
        )
        self.harness.charm.on.start.emit()

        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("failed to open TCP port for MongoDB")
        )

    @patch("charm.check_call")
    def test_set_port(self, _call):
        self.harness.charm._open_port_tcp(27017)
        # Make sure the port is opened and the service is started
        self.assertEqual(_call.call_args_list, [call(["open-port", "27017/TCP"])])

    @patch("charm.check_call")
    def test_set_port_failure(self, _call):
        _call.side_effect = subprocess.CalledProcessError(cmd="open-port 27017/TCP", returncode=1)

        with self.assertRaises(subprocess.CalledProcessError):
            with self.assertLogs("charm", "ERROR") as logs:
                self.harness.charm._open_port_tcp(27017)
                self.assertIn("failed opening port 27017", "".join(logs.output))

    @patch("charm.apt.add_package")
    @patch("charm.apt.update")
    def test_install_apt_packages_sucess(self, update, add_package):
        self.harness.charm._install_apt_packages(["test-package"])
        update.assert_called()
        add_package.assert_called_with(["test-package"])

    @patch("charm.apt.add_package")
    @patch("charm.apt.update")
    def test_install_apt_packages_update_failure(self, update, add_package):
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

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    @patch("charm.apt.DebianRepository.import_key")
    def test_add_repository_success(self, import_key, from_repo_line, repo_map):
        # preset values
        repo_map.return_value = set()
        req = requests.get(GPG_URL)
        mongodb_public_key = req.text

        # verify we add the MongoDB repository
        repos = self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)
        from_repo_line.assert_called()
        (from_repo_line.return_value.import_key).assert_called_with(mongodb_public_key)
        self.assertEqual(repos, {from_repo_line.return_value})

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    @patch("charm.urlopen")
    def test_add_repository_gpg_fail_leads_to_blocked(self, urlopen, from_repo_line, repo_map):
        # preset values
        repo_map.return_value = set()
        urlopen.side_effect = URLError("urlopen error")
        self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)

        # verify we don't add repo when an exception occurs and that we enter blocked state
        self.assertEqual(repo_map.return_value, set())
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    def test_add_repository_cant_create_list_file_blocks(self, from_repo_line, repo_map):
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
        # verify an exception is raised when we cannot import GPG key
        with self.assertRaises(apt.GPGKeyError):
            (from_repo_line.return_value.import_key).side_effect = apt.GPGKeyError(
                "import key error"
            )
            self.harness.charm._add_repository(REPO_NAME, GPG_URL, REPO_ENTRY)

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    def test_add_repository_already_added(self, from_repo_line, repo_map):
        # preset value
        repo_map.return_value = REPO_MAP

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
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.set_leader(False)
        self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)

        reconfigure.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_mongodb_relation_joined_peers_not_ready(self, single_replica, mongo_reconfigure):
        # preset values
        self.harness.set_leader(True)
        single_replica.return_value.is_ready.return_value = False

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
        # preset values
        self.harness.set_leader(True)
        single_replica.return_value.is_ready.return_value = True
        self.harness.charm._need_replica_set_reconfiguration = True

        # test cases where replica set should and shouldn't be reconfigured
        exceptions = [
            ConnectionFailure("error message"),
            ConfigurationError("error message"),
            OperationFailure("error message"),
        ]
        for exception in exceptions:
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
        # preset values
        self.harness.charm._need_replica_set_reconfiguration = True
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

    @patch("os.environ.get")
    @patch("charm.MongodbOperatorCharm._reconfigure")
    @patch("charm.MongodbOperatorCharm._primary")
    def test_mongodb_departed_non_leader_does_nothing(self, primary, reconfigure, _):
        # preset values
        self.harness.set_leader(False)
        mock_event = mock.Mock()

        self.harness.charm._on_mongodb_relation_departed(mock_event)
        reconfigure.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._primary")
    @patch("os.environ.get")
    @patch("mongod_helpers.MongoDB.primary_step_down")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    @patch("charm.MongodbOperatorCharm._need_replica_set_reconfiguration")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    def test_on_mongodb_relation_departed_primary_removed(
        self,
        mongodb_reconfigure,
        need_reconfiguration,
        single_replica,
        primary_step_down,
        departing_unit,
        primary,
    ):
        """Test removing primary replica.

        Verifies relation_departed operations for when the departing unit is the primary replica.
        """
        # preset values
        self.harness.charm._need_replica_set_reconfiguration = True
        # cannot hard set this since its used in other locations
        self.harness.charm.unit.name = "mongodb/1"
        departing_unit.return_value = "mongodb/1"
        self.harness.charm._primary = "mongodb/1"

        # add peer unit
        rel = self.harness.charm.model.get_relation("mongodb")
        key_values = {"private-address": "127.4.5.6"}
        self.harness.add_relation_unit(rel.id, "mongodb/1")
        self.harness.update_relation_data(rel.id, "mongodb/1", key_values)

        # remove unit to trigger event
        self.harness.remove_relation_unit(rel.id, "mongodb/1")

        # verify we call the step down method
        primary_step_down.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._primary")
    @patch("os.environ.get")
    @patch("mongod_helpers.MongoDB.primary_step_down")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    @patch("charm.MongodbOperatorCharm._need_replica_set_reconfiguration")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    def test_on_mongodb_relation_departed_primary_removed_failure(
        self,
        mongodb_reconfigure,
        need_reconfiguration,
        single_replica,
        primary_step_down,
        departing_unit,
        primary,
    ):
        """Test removing primary replica leads to failure.

        Verifies relation_departed operations for when the departing unit is a primary and
        a failure occurs in attempying to step down the primary replica.
        """
        # preset values
        self.harness.charm._need_replica_set_reconfiguration = True
        self.harness.charm.unit.name = "mongodb/0"
        departing_unit.return_value = "mongodb/0"
        self.harness.charm._primary = "mongodb/0"
        self.harness.set_leader(True)

        exceptions = [
            ConnectionFailure("connection error message"),
            ConfigurationError("configuration error message"),
            OperationFailure("operation error message"),
        ]

        # check that each exception is handled properly
        for exception in exceptions:
            primary_step_down.side_effect = exception

            # add peer unit
            rel = self.harness.charm.model.get_relation("mongodb")
            rel_id = rel.id
            key_values = {"private-address": "127.4.5.6"}
            self.harness.add_relation_unit(rel_id, "mongodb/1")
            self.harness.update_relation_data(rel_id, "mongodb/1", key_values)

            # remove unit to trigger event
            self.harness.remove_relation_unit(rel_id, "mongodb/1")

            # verify waiting status
            self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))

            # verify we don't reconfigure
            mongodb_reconfigure.assert_called()

            # verify we don't update
            self.assertEqual(
                self.harness.charm._replica_set_hosts,
                ["127.4.5.6", "1.1.1.1"],
            )

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._peers")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("charm.MongodbOperatorCharm.app")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_initialise_replica_failure_leads_to_waiting_state(
        self, is_replica, app, service_resume, _, initialise_replica_set, is_ready, peers
    ):
        # set peer data so that leader doesn't reconfigure set on set_leader
        peers_data = {}
        peers_data[app] = {
            "_new_leader_must_reconfigure": "False",
        }
        peers.data = peers_data

        self.harness.set_leader(True)
        is_ready.return_value = True
        app.planned_units.return_value = 1
        is_replica.return_value = False
        exceptions = [
            ConnectionFailure("connection error message"),
            ConfigurationError("configuration error message"),
            OperationFailure("operation error message"),
        ]
        log_messages = [
            "ERROR:charm:error initialising replica sets in _on_start: error: connection error message",
            "ERROR:charm:error initialising replica sets in _on_start: error: configuration error message",
        ]
        for exception, log_message in zip(exceptions, log_messages):
            with self.assertLogs("charm", "DEBUG") as logs:
                initialise_replica_set.side_effect = exception
                self.harness.charm.on.start.emit()
                initialise_replica_set.assert_called()
                self.assertIn(log_message, logs.output)

            self.assertEqual(
                self.harness.charm.unit.status, WaitingStatus("waiting to initialise replica set")
            )

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_running")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_initialise_replica_success(
        self, is_replica, service_running, _open_port_tcp, initialise_replica_set, is_ready
    ):
        self.harness.set_leader(True)
        service_running.return_value = True
        is_ready.return_value = True
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
        ip_address = "1.1.1.1"
        mongo_replica = self.harness.charm._single_mongo_replica(ip_address)
        self.assertEqual(mongo_replica._calling_unit_ip, ip_address)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_update_status_primary(self, single_replica):
        single_replica.return_value._is_primary = True
        self.harness.charm.on.update_status.emit()
        single_replica.assert_called_with("1.1.1.1")
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("Replica set primary"))

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    @patch("ops.model.ActiveStatus")
    def test_update_status_secondary(self, active_status, single_replica):
        single_replica.return_value._is_primary = False
        self.harness.charm.on.update_status.emit()
        single_replica.assert_called_with("1.1.1.1")
        active_status.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_get_primary_current_unit_primary(self, single_replica):
        single_replica.return_value._is_primary = True
        mock_event = mock.Mock()
        self.harness.charm._on_get_primary_action(mock_event)
        mock_event.set_results.assert_called_with({"replica-set-primary": "mongodb/0"})

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_get_primary_peer_unit_primary(self, single_replica):
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out the self unit not being primary but its peer being primary
        mock_self_unit = mock.Mock()
        mock_self_unit._is_primary = False
        mock_peer_unit = mock.Mock()
        mock_peer_unit._is_primary = True
        single_replica.side_effect = [mock_self_unit, mock_peer_unit]

        mock_event = mock.Mock()

        self.harness.charm._on_get_primary_action(mock_event)
        mock_event.set_results.assert_called_with({"replica-set-primary": "mongodb/1"})

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_primary_no_primary(self, single_replica):
        """Test that that the primary property can handle the case when there is no primary.

        Verifies that when there is no primary, the property _primary returns None.
        """
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out no units being primary
        single_replica.return_value._is_primary = False

        # verify no primary identified
        primary = self.harness.charm._primary
        self.assertEqual(primary, None)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_primary_self_primary(self, single_replica):
        """Test that that the primary property can identify itself as primary.

        Verifies that when the calling unit is primary, the calling unit is identified as primary.
        """
        single_replica.return_value._is_primary = True

        primary = self.harness.charm._primary
        self.assertEqual(primary, "mongodb/0")

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_primary_peer_primary(self, single_replica):
        """Test that that the primary property can identify a peer unit as primary.

        Verifies that when a non-calling unit is primary, the non-calling unit is identified as
        primary.
        """
        # add peer unit
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", {"private-address": "2.2.2.2"})

        # mock out the self unit not being primary but its peer being primary
        mock_self_unit = mock.Mock()
        mock_self_unit._is_primary = False
        mock_peer_unit = mock.Mock()
        mock_peer_unit._is_primary = True
        single_replica.side_effect = [mock_self_unit, mock_peer_unit]

        primary = self.harness.charm._primary
        self.assertEqual(primary, "mongodb/1")

    @patch("charm.MongodbOperatorCharm._unit_ips")
    @patch("charm.MongodbOperatorCharm._replica_set_hosts")
    def test_need_replica_set_reconfiguration(self, units, hosts):
        self.harness.charm._unit_ips = ["1.1.1.1", "2.2.2.2"]
        self.harness.charm._replica_set_hosts = ["1.1.1.1"]
        self.assertEqual(self.harness.charm._need_replica_set_reconfiguration, True)

        self.harness.charm._unit_ips = ["1.1.1.1", "2.2.2.2"]
        self.harness.charm._replica_set_hosts = ["1.1.1.1", "2.2.2.2"]
        self.assertEqual(self.harness.charm._need_replica_set_reconfiguration, False)

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.reconfigure_replica_set")
    @patch("charm.MongodbOperatorCharm._peers")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    @patch("charm.MongodbOperatorCharm._need_replica_set_reconfiguration")
    def test_on_leader_elected_waits_for_primary(self, _, single_replica, peers, reconfigure):
        """Test that leader elected will wait for a new primary before reconfiguring.

        Verifies that if the leader needs to reconfigure the replica set it will wait for a primary
        to be elected
        """
        # preset values
        self.harness.charm._need_replica_set_reconfiguration = True
        single_replica.return_value._is_primary = False

        # peers data values are string because relation data only supports strings
        peers_data = {}
        peers_data[self.harness.charm.app] = {
            "_new_leader_must_reconfigure": "True",
            "replica_set_hosts": '["1.1.1.1", "127.4.5.6"]',
        }
        peers.data = peers_data
        self.harness.charm.on.leader_elected.emit()

        # check that we don't reconfigure and that reconfiguration is still needed
        reconfigure.assert_not_called()
        self.assertTrue(isinstance(self.harness.charm.unit.status, WaitingStatus))
        self.assertEqual(
            peers_data[self.harness.charm.app]["_new_leader_must_reconfigure"], "True"
        )
        self.assertEqual(
            self.harness.charm._replica_set_hosts,
            ["1.1.1.1", "127.4.5.6"],
        )

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._reconfigure")
    @patch("charm.MongodbOperatorCharm._peers")
    @patch("charm.MongodbOperatorCharm._single_mongo_replica")
    def test_on_leader_elected_updates_relation_data(self, single_replica, peers, reconfigure):
        """Test that leader elected properly handles relation data.

        Verifies that if the leader needs to reconfigure the replica set, that after it
        reconfigures it will reset the relation data.
        """
        # preset values
        single_replica.return_value._is_primary = True

        # peers data values are string because relation data only supports strings
        peers_data = {}
        peers_data[self.harness.charm.app] = {
            "_new_leader_must_reconfigure": "True",
        }
        peers.data = peers_data
        self.harness.charm.on.leader_elected.emit()

        # check that we don't reconfigure and that reconfiguration is still needed
        reconfigure.assert_called()
        self.assertEqual(
            peers.data[self.harness.charm.app]["_new_leader_must_reconfigure"], "False"
        )
