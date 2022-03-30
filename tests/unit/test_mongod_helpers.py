# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from pymongo import MongoClient
from tenacity import RetryError

from mongod_helpers import (
    ConfigurationError,
    ConnectionFailure,
    MongoDB,
    OperationFailure,
)

MONGO_CONFIG = {
    "app_name": "mongodb",
    "replica_set_name": "rs0",
    "num_hosts": 2,
    "port": 27017,
    "root_password": "password",
    "unit_ips": ["1.1.1.1", "2.2.2.2"],
    "calling_unit_ip": ["1.1.1.1"],
    "replica_set_hosts": ["1.1.1.1", "2.2.2.2"],
}

PYMONGO_EXCEPTIONS = [
    (ConnectionFailure("error message"), ConnectionFailure),
    (ConfigurationError("error message"), ConfigurationError),
    (OperationFailure("error message"), OperationFailure),
]


class TestMongoServer(unittest.TestCase):
    def test_client_returns_mongo_client_instance(self):
        """Test that client returns an instance of MongoClient."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        standalone_status = [True, False]
        for standalone in standalone_status:
            client = mongo.client(standalone)
            self.assertIsInstance(client, MongoClient)

    @patch("pymongo.MongoClient.server_info")
    def test_mongo_is_ready_when_server_info_is_available(self, server_info):
        """Test that is ready returns true when mongod is running."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        server_info.return_value = {"info": "some info"}

        standalone_status = [True, False]
        for standalone in standalone_status:
            ready = mongo.is_mongod_ready()
            self.assertEqual(ready, True)

    @patch("mongod_helpers.MongoDB.check_server_info")
    @patch("pymongo.MongoClient", "server_info", "ServerSelectionTimeoutError")
    def test_mongo_is_not_ready_when_server_info_is_not_available(self, check_server_info):
        """Test that is ready returns False when mongod is not running."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        check_server_info.side_effect = RetryError(last_attempt=None)

        standalone_status = [True, False]
        for standalone in standalone_status:
            ready = mongo.is_mongod_ready()
            self.assertEqual(ready, False)

    def test_replica_set_uri_contains_correct_number_of_hosts(self):
        """Test that is replica set URI uses the expected number of hosts."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        standalone_status = [False, True]
        expected_hosts_by_status = [len(config["unit_ips"]), 1]

        for standalone, expected_hosts in zip(standalone_status, expected_hosts_by_status):
            uri = mongo.replica_uri(standalone)
            host_list = uri.split(",")
            self.assertEqual(len(host_list), expected_hosts)

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_initializing_replica_invokes_admin_command(self, mock_client, client):
        """Test that when initializing replica set replSetInitiate command is used."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        client.return_value = mock_client

        hosts = {}
        for i in range(config["num_hosts"]):
            hosts[i] = "host{}".format(i)

        mongo.initialise_replica_set(hosts)
        mock_client.admin.command.assert_called()
        command, _ = mock_client.admin.command.call_args
        self.assertEqual("replSetInitiate", command[0])

    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=False)
    def test_is_replica_set_not_ready_returns_false(self, is_ready):
        """Test that is replica set status returns false when mongod isn't running."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        replica_set_status = mongo.is_replica_set()
        self.assertEqual(replica_set_status, False)

    @patch("pymongo.collection.Collection.find")
    @patch("pymongo.MongoClient.close")
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    def test_is_replica_set_is_replica_returns_true(self, is_ready, close, find):
        """Test that is replica set status returns true when configured as a replica set."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        find.return_value = [{"_id": "rs0"}]

        replica_set_status = mongo.is_replica_set()
        close.assert_called()
        self.assertEqual(replica_set_status, True)

    @patch("pymongo.collection.Collection.find")
    @patch("pymongo.MongoClient.close")
    @patch("mongod_helpers.MongoDB.is_mongod_ready", return_value=True)
    def test_is_replica_set_is_not_replica_returns_false(self, is_ready, close, find):
        """Test that is replica set status returns false when not configured as a replica set."""
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        find.side_effect = IndexError()

        replica_set_status = mongo.is_replica_set()
        close.assert_called()
        self.assertEqual(replica_set_status, False)

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_reconfiguring_replica_invokes_admin_command(self, mock_client, client):
        """Test that reconfiguring replica set uses the replSetReconfig admin command."""
        # presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify we make a call to replSetReconfig
        mongo.reconfigure_replica_set()
        mock_client.admin.command.assert_called()
        (command, _), _ = mock_client.admin.command.call_args
        self.assertEqual("replSetReconfig", command)

        # verify we close connection
        (mock_client.close).assert_called()

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_reconfiguring_replica_handles_failure(self, mock_client, client):
        """Test on failure of reconfiguring replica set an exception is raised.

        Test also verifies that when an exception is raised we still close the client connection.
        """
        # presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify we raise an exception on reconfigure failure
        for exception, expected_raise in PYMONGO_EXCEPTIONS:
            with self.assertRaises(expected_raise):
                mock_client.admin.command.side_effect = exception

                # call function
                mongo.reconfigure_replica_set()

            # verify we close connection
            (mock_client.close).assert_called()

    def test_replica_set_config_no_changes(self):
        """Test replica_set_config doesn't update the config when no changes are needed."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        current_config = {}
        current_config["config"] = {}
        current_config["config"]["members"] = [
            {"host": "1.1.1.1:27017", "_id": 0},
            {"host": "2.2.2.2:27017", "_id": 1},
        ]

        new_config = mongo.replica_set_config(current_config)
        self.assertEqual(new_config, current_config["config"]["members"])

    def test_replica_set_config_adds_member(self):
        """Test replica_set_config adds member properly.

        Verifies that the old host machines maintains its original id in the config and that the
        new host gets an id of the next increment.
        """
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        current_config = {}
        current_config["config"] = {}
        current_config["config"]["members"] = [{"host": "1.1.1.1:27017", "_id": 0}]

        expected_new_members = [
            {"host": "1.1.1.1:27017", "_id": 0},
            {"host": "2.2.2.2:27017", "_id": 1},
        ]
        new_config = mongo.replica_set_config(current_config)
        self.assertEqual(new_config, expected_new_members)

    def test_replica_set_config_removes_member(self):
        """Test replica_set_config removes member properly.

        Verifies that the host machines not getting removed maintain their original id.
        """
        # standard presets
        config = MONGO_CONFIG.copy()
        # remove a member
        config["unit_ips"] = ["2.2.2.2"]
        mongo = MongoDB(config)

        current_config = {}
        current_config["config"] = {}
        current_config["config"]["members"] = [
            {"host": "1.1.1.1:27017", "_id": 0},
            {"host": "2.2.2.2:27017", "_id": 1},
        ]

        expected_new_members = [
            {"host": "2.2.2.2:27017", "_id": 1},
        ]
        new_config = mongo.replica_set_config(current_config)
        self.assertEqual(new_config, expected_new_members)

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_primary_step_down(self, mock_client, client):
        """Verifies that primary_step_down calls the necessary replSetStepDown command."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        mongo.primary_step_down()
        mock_client.admin.command.assert_called()
        command, _ = mock_client.admin.command.call_args
        self.assertEqual("replSetStepDown", command[0])

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_primary_step_down_failure(self, mock_client, client):
        """Verifies that primary_step_down appropriately handles exceptions."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify that we raise the correct exception
        for exception, expected_raise in PYMONGO_EXCEPTIONS:
            with self.assertRaises(expected_raise):
                mock_client.admin.command.side_effect = exception
                mongo.primary_step_down()

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_primary_failure(self, mock_client, client):
        """Verifies that primary appropriately handles exceptions."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify that we raise the correct exception
        for exception, expected_raise in PYMONGO_EXCEPTIONS:
            with self.assertRaises(expected_raise):
                mock_client.admin.command.side_effect = exception
                mongo.primary()

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_remove_replica_failure(self, mock_client, client):
        """Verifies that remove_replica appropriately handles exceptions."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify that we raise the correct exception
        for exception, expected_raise in PYMONGO_EXCEPTIONS:
            with self.assertRaises(expected_raise):
                mock_client.admin.command.side_effect = exception
                mongo.primary_step_down()
            mock_client.close.assert_called()

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_is_replica_ready_status_error(self, mock_client, client):
        """Verifies that is_replica_ready appropriately handles exceptions."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify that we raise the correct exception
        for exception, expected_raise in PYMONGO_EXCEPTIONS:
            mock_client.admin.command.side_effect = exception
            ready = mongo.is_replica_ready()
            self.assertEqual(ready, False)

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_check_replica_status_error(self, mock_client, client):
        """Verifies that check_replica_status appropriately handles exceptions."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify that we raise the correct exception
        for exception, expected_raise in PYMONGO_EXCEPTIONS:
            with self.assertRaises(expected_raise):
                mock_client.admin.command.side_effect = exception
                mongo.check_replica_status("1.1.1.1")
            mock_client.close.assert_called()

    @patch("mongod_helpers.MongoDB.is_replica_ready", return_value=False)
    @patch("pymongo.MongoClient")
    @patch("mongod_helpers.MongoDB.client")
    def test_not_all_replicas_ready(self, is_replica_ready, mock_client, client):
        """Verifies that all_replicas_ready returns False when not all replicas are ready."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        # verify result of all replicas ready
        self.assertEqual(mongo.all_replicas_ready(), False)

    @patch("mongod_helpers.MongoDB.check_replica_status")
    @patch("pymongo.MongoClient")
    @patch("mongod_helpers.MongoDB.client")
    def test_not_all_replicas_check_failure(self, check_replica_status, mock_client, client):
        """Verifies that all_replicas_ready returns False failure to check status occurs."""
        # standard presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        for exception in PYMONGO_EXCEPTIONS:
            check_replica_status.side_effect = exception

            # verify result of all replicas ready
            self.assertEqual(mongo.all_replicas_ready(), False)
