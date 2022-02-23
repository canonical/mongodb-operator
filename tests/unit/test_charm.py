# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from typing import List
from unittest import mock
from unittest.mock import MagicMock, call, mock_open, patch

import requests
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.testing import Harness

from charm import (
    ConfigurationError,
    ConnectionFailure,
    MongodbOperatorCharm,
    URLError,
    apt,
    subprocess,
)
from tests.unit.helpers import patch_network_get


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

    @patch("charm.MongodbOperatorCharm._add_mongodb_org_repository")
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
    def test_add_mongodb_org_repository_success(self, import_key, from_repo_line, repo_map):
        # repo_map.return_value = MagicMock()
        repo_map.return_value = set()
        req = requests.get("https://www.mongodb.org/static/pgp/server-5.0.asc")
        mongodb_public_key = req.text

        self.harness.charm._add_mongodb_org_repository()
        from_repo_line.assert_called()
        (from_repo_line.return_value.import_key).assert_called_with(mongodb_public_key)
        # TODO: figure out the right way to verify repo map
        # repo_map.return_value.add.assert_called_with(from_repo_line.return_value)
        self.assertEqual(repo_map.return_value, {from_repo_line.return_value})

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    @patch("charm.apt.DebianRepository.import_key")
    @patch("charm.urlopen")
    def test_add_mongodb_org_repository_gpg_fail_leads_to_blocked(
        self, urlopen, import_key, from_repo_line, repo_map
    ):
        # preset values
        # repo_map.return_value = MagicMock()
        repo_map.return_value = set()
        urlopen.side_effect = URLError("urlopen error")
        self.harness.charm._add_mongodb_org_repository()

        # verify we don't add repo when an exception occurs and that we enter blocked state
        # TODO: figure out the right way to verify repo map
        # repo_map.return_value.add.assert_not_called()
        self.assertEqual(repo_map.return_value, set())
        self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    def test_add_mongodb_org_repository_cant_create_list_file_blocks(
        self, from_repo_line, repo_map
    ):
        exceptions = [
            apt.InvalidSourceError("invalid source message"),
            ValueError("value message"),
        ]
        for exception in exceptions:
            from_repo_line.side_effect = exception
            self.harness.charm._add_mongodb_org_repository()

            # verify that when an exception occurs we enter blocked state
            self.assertTrue(isinstance(self.harness.charm.unit.status, BlockedStatus))

    @patch("charm.apt.RepositoryMapping")
    @patch("charm.apt.DebianRepository.from_repo_line")
    @patch("charm.apt.DebianRepository.import_key")
    def test_add_mongodb_org_repository_already_added_skips(
        self, import_key, from_repo_line, repo_map
    ):
        # repo_map.return_value = MagicMock(
        #     return_value={"deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"}
        # )
        REPO_MAP = {"deb-https://repo.mongodb.org/apt/ubuntu-focal/mongodb-org/5.0"}
        repo_map.return_value = REPO_MAP

        # verify we don't add repo when we already have repo
        self.harness.charm._add_mongodb_org_repository()
        # TODO: figure out the right way to verify repo map
        # repo_map.return_value.add.assert_not_called()
        self.assertEqual(repo_map.return_value, REPO_MAP)

    @patch_network_get(private_address="1.1.1.1")
    def test_unit_ips(self):
        key_values = {"private-address": "127.4.5.6"}
        rel_id = self.harness.charm.model.get_relation("mongodb").id
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", key_values)

        resulting_ips = self.harness.charm._unit_ips
        expected_ips = ["127.4.5.6", "1.1.1.1"]
        self.assertEqual(resulting_ips, expected_ips)

    @patch("charm.MongodbOperatorCharm.app")
    def test_mongodb_relation_joined_non_leader_does_nothing(self, app):
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.set_leader(False)
        self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)

        app.planned_units.assert_not_called()

    @patch("charm.MongodbOperatorCharm.app")
    def test_mongodb_relation_joined_planned_units_does_not_match_joined_units(self, app):
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.set_leader(True)
        app.planned_units.return_value = 3

        with self.assertLogs("charm", "DEBUG") as logs:
            self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)
            self.assertIn(
                "planned units does not match joined units: 3 != 1",
                "".join(logs.output),
            )

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    @patch("charm.MongodbOperatorCharm.app")
    def test_mongodb_relation_joined_already_replica_set(
        self, app, is_replica_set, is_ready, initialise_replica_set
    ):
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.set_leader(True)
        app.planned_units.return_value = len(self.harness.charm._unit_ips)
        is_replica_set.return_value = True
        ready_statuses = [True, False]

        with self.assertLogs("charm", "DEBUG") as logs:
            for ready_status in ready_statuses:
                is_ready.return_value = ready_status
                self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)
                # verify that we do not re-initialise replica set
                initialise_replica_set.assert_not_called()

                # check behavior based on ready status
                is_ready.assert_called()
                if ready_status:
                    continue

                self.assertIn(
                    "Replica set for units: ['1.1.1.1'], is not ready", "".join(logs.output)
                )
                self.assertEqual(
                    self.harness.charm.unit.status,
                    BlockedStatus("failed to initialise replica set"),
                )

        @patch_network_get(private_address="1.1.1.1")
        @patch("charm.MongodbOperatorCharm._initialise_replica_set")
        @patch("mongod_helpers.MongoDB.is_ready")
        @patch("mongod_helpers.MongoDB.is_replica_set")
        @patch("charm.MongodbOperatorCharm.app")
        def test_mongodb_relation_joined_not_yet_replica_set(
            self, app, is_replica_set, is_ready, initialise_replica_set
        ):
            rel = self.harness.charm.model.get_relation("mongodb")
            self.harness.set_leader(True)
            app.planned_units.return_value = len(self.harness.charm._unit_ips)
            is_replica_set.return_value = False
            ready_statuses = [True, False]

            with self.assertLogs("charm", "DEBUG") as logs:
                for ready_status in ready_statuses:
                    is_ready.return_value = ready_status
                    self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)
                    # verify that we do initialise replica set
                    initialise_replica_set.assert_called()

                    # check behavior based on ready status
                    is_ready.assert_called()
                    if ready_status:
                        continue

                    self.assertIn(
                        "Replica set for units: ['1.1.1.1'], is not ready", "".join(logs.output)
                    )
                    self.assertEqual(
                        self.harness.charm.unit.status,
                        BlockedStatus("failed to initialise replica set"),
                    )

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("charm.MongodbOperatorCharm.app")
    def test_mongodb_relation_joined_peers_not_ready(self, app, is_ready, initialise_replica_set):
        # preset values
        self.harness.set_leader(True)
        is_ready.return_value = False

        # simulate 2nd MongoDB unit
        rel = self.harness.charm.model.get_relation("mongodb")
        rel_id = rel.id
        key_values = {"private-address": "127.4.5.6"}
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", key_values)
        app.planned_units.return_value = len(self.harness.charm._unit_ips)

        with self.assertLogs("charm", "DEBUG") as logs:
            self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)

            self.assertIn(
                "unit: <ops.model.Unit mongodb/1> is not ready, cannot "
                + "initialise replica set until all units are ready, deferring "
                + "on relation-joined",
                "".join(logs.output),
            )

            # verify that we do not initialise replica set
            initialise_replica_set.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    @patch("charm.MongodbOperatorCharm._initialise_replica_set")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("charm.MongodbOperatorCharm.app")
    def test_mongodb_relation_joined_peers_ready(
        self, app, is_ready, initialise_replica_set, is_replica_set
    ):
        # preset values
        self.harness.set_leader(True)
        is_ready.return_value = True
        is_replica_set.return_value = False

        # simulate 2nd MongoDB unit
        rel = self.harness.charm.model.get_relation("mongodb")
        rel_id = rel.id
        key_values = {"private-address": "127.4.5.6"}
        self.harness.add_relation_unit(rel_id, "mongodb/1")
        self.harness.update_relation_data(rel_id, "mongodb/1", key_values)
        app.planned_units.return_value = len(self.harness.charm._unit_ips)

        self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)

        # verify that we do not initialise replica set
        initialise_replica_set.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_resume")
    @patch("charm.MongodbOperatorCharm.app")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_initialise_replica_failure_leads_to_waiting_state(
        self, is_replica, app, service_resume, _, initialise_replica_set, is_ready
    ):
        self.harness.set_leader(True)
        is_ready.return_value = True
        app.planned_units.return_value = 1
        is_replica.return_value = False
        exceptions = [
            ConnectionFailure("connection error message"),
            ConfigurationError("configuration error message"),
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
        self.assertEqual(
            self.harness.charm._peers.data[self.harness.charm.app]["replica_set_hosts"],
            '"1.1.1.1"',
        )

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus(""))

    @patch_network_get(private_address="1.1.1.1")
    @patch("mongod_helpers.MongoDB.is_ready")
    @patch("mongod_helpers.MongoDB.initialise_replica_set")
    @patch("charm.MongodbOperatorCharm._open_port_tcp")
    @patch("charm.service_running")
    @patch("mongod_helpers.MongoDB.is_replica_set")
    def test_initialise_replica_only_once(
        self, is_replica, service_running, _open_port_tcp, initialise_replica_set, is_ready
    ):
        self.harness.set_leader(True)
        is_ready.return_value = True
        is_replica.side_effect = [False, True, True]

        # emit both events
        self.harness.charm.on.start.emit()
        rel = self.harness.charm.model.get_relation("mongodb")
        self.harness.charm.on.mongodb_relation_joined.emit(relation=rel)

        initialise_replica_set.assert_called_once()
        is_replica.assert_called()

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
