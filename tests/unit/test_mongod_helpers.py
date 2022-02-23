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
}


class TestMongoServer(unittest.TestCase):
    def test_client_returns_mongo_client_instance(self):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        standalone_status = [True, False]
        for standalone in standalone_status:
            client = mongo.client(standalone)
            self.assertIsInstance(client, MongoClient)

    @patch("pymongo.MongoClient.server_info")
    def test_mongo_is_ready_when_server_info_is_available(self, server_info):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        server_info.return_value = {"info": "some info"}

        standalone_status = [True, False]
        for standalone in standalone_status:
            ready = mongo.is_ready(standalone)
            self.assertEqual(ready, True)

    @patch("mongod_helpers.MongoDB.check_server_info")
    @patch("pymongo.MongoClient", "server_info", "ServerSelectionTimeoutError")
    def test_mongo_is_not_ready_when_server_info_is_not_available(self, check_server_info):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        check_server_info.side_effect = RetryError(last_attempt=None)

        standalone_status = [True, False]
        for standalone in standalone_status:
            ready = mongo.is_ready(standalone)
            self.assertEqual(ready, False)

    def test_replica_set_uri_contains_correct_number_of_hosts(self):
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

    @patch("mongod_helpers.MongoDB.is_ready")
    def test_is_replica_set_not_ready_returns_false(self, is_ready):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        is_ready.return_value = False

        replica_set_status = mongo.is_replica_set()
        self.assertEqual(replica_set_status, False)

    @patch("pymongo.collection.Collection.find")
    @patch("pymongo.MongoClient.close")
    @patch("mongod_helpers.MongoDB.is_ready")
    def test_is_replica_set_is_replica_returns_true(self, is_ready, close, find):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        is_ready.return_value = True

        find.return_value = [{"_id": "rs0"}]

        replica_set_status = mongo.is_replica_set()
        close.assert_called()
        self.assertEqual(replica_set_status, True)

    @patch("pymongo.collection.Collection.find")
    @patch("pymongo.MongoClient.close")
    @patch("mongod_helpers.MongoDB.is_ready")
    def test_is_replica_set_is_not_replica_returns_false(self, is_ready, close, find):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        is_ready.return_value = True

        find.side_effect = IndexError()

        replica_set_status = mongo.is_replica_set()
        close.assert_called()
        self.assertEqual(replica_set_status, False)

    @patch("mongod_helpers.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_reconfiguring_replica_invokes_admin_command(self, mock_client, client):
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
        # presets
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        client.return_value = mock_client

        # verify we make a call to reconfigure
        exceptions = [
            ConnectionFailure("error message"),
            ConfigurationError("error message"),
            OperationFailure("error message"),
        ]
        raises = [ConnectionFailure, ConfigurationError, OperationFailure]
        for exception, expected_raise in zip(exceptions, raises):
            with self.assertRaises(expected_raise):
                mock_client.admin.command.side_effect = exception

                # call function
                mongo.reconfigure_replica_set()

                # verify we close connection
                (mock_client.close).assert_called()

    def test_replica_set_config_no_changes(self):
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
