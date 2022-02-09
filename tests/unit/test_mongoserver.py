# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from pymongo import MongoClient
from tenacity import RetryError

from mongoserver import MongoDB

MONGO_CONFIG = {
    "app_name": "mongodb",
    "replica_set_name": "rs0",
    "num_peers": 1,
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

    @patch("mongoserver.MongoDB.check_server_info")
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

    @patch("mongoserver.MongoDB.client")
    @patch("pymongo.MongoClient")
    def test_initializing_replica_invokes_admin_command(self, mock_client, client):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)

        client.return_value = mock_client

        hosts = {}
        for i in range(config["num_peers"]):
            hosts[i] = "host{}".format(i)

        mongo.initialise_replica_set(hosts)
        mock_client.admin.command.assert_called()
        command, _ = mock_client.admin.command.call_args
        self.assertEqual("replSetInitiate", command[0])

    @patch("mongoserver.MongoDB.is_ready")
    def test_is_replica_set_not_ready_returns_false(self, is_ready):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        is_ready.return_value = False

        replica_set_status = mongo.is_replica_set()
        self.assertEqual(replica_set_status, False)

    @patch("pymongo.collection.Collection.find")
    @patch("pymongo.MongoClient.close")
    @patch("mongoserver.MongoDB.is_ready")
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
    @patch("mongoserver.MongoDB.is_ready")
    def test_is_replica_set_is_not_replica_returns_false(self, is_ready, close, find):
        config = MONGO_CONFIG.copy()
        mongo = MongoDB(config)
        is_ready.return_value = True

        find.side_effect = IndexError()

        replica_set_status = mongo.is_replica_set()
        close.assert_called()
        self.assertEqual(replica_set_status, False)
