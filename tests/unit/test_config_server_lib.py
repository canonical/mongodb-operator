# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest import mock

from ops.testing import Harness

from charm import MongodbOperatorCharm

from .helpers import patch_network_get

RELATION_NAME = "s3-credentials"


class TestConfigServerInterface(unittest.TestCase):
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self):
        self.harness = Harness(MongodbOperatorCharm)
        self.harness.begin()
        self.harness.add_relation("database-peers", "database-peers")
        self.harness.set_leader(True)
        self.charm = self.harness.charm
        self.addCleanup(self.harness.cleanup)

    def test_on_relation_joined_failed_hook_checks(self):
        """Tests that no relation data is set when cluster joining conditions are not met."""

        def is_not_config_mock_call(*args):
            assert args == ("config-server",)
            return False

        self.harness.charm.app_peer_data["db_initialised"] = "True"

        # fails due to being run on non-config-server
        self.harness.charm.is_role = is_not_config_mock_call
        relation_id = self.harness.add_relation("cluster", "mongos")
        self.harness.add_relation_unit(relation_id, "mongos/0")
        self.harness.charm.cluster.database_provides.update_relation_data = mock.Mock()
        self.harness.charm.cluster.database_provides.update_relation_data.assert_not_called()

        # fails because db has not been initialized
        del self.harness.charm.app_peer_data["db_initialised"]

        def is_config_mock_call(*args):
            assert args == ("config-server",)
            return True

        self.harness.charm.is_role = is_config_mock_call
        self.harness.add_relation_unit(relation_id, "mongos/1")
        self.harness.charm.cluster.database_provides.update_relation_data.assert_not_called()

        # fails because not leader
        self.harness.set_leader(False)
        self.harness.add_relation_unit(relation_id, "mongos/2")
        self.harness.charm.cluster.database_provides.update_relation_data.assert_not_called()

    def test_update_rel_data_failed_hook_checks(self):
        """Tests that no relation data is set when the cluster is not ready."""

        def is_not_config_mock_call(*args):
            assert args == ("config-server",)
            return False

        self.harness.charm.app_peer_data["db_initialised"] = "True"

        # fails due to being run on non-config-server
        self.harness.charm.is_role = is_not_config_mock_call
        self.harness.charm.cluster.update_config_server_db(mock.Mock())
        self.harness.charm.cluster.database_provides.update_relation_data = mock.Mock()
        self.harness.charm.cluster.database_provides.update_relation_data.assert_not_called()

        # fails because db has not been initialized
        del self.harness.charm.app_peer_data["db_initialised"]

        def is_config_mock_call(*args):
            assert args == ("config-server",)
            return True

        self.harness.charm.is_role = is_config_mock_call
        self.harness.charm.cluster.update_config_server_db(mock.Mock())
        self.harness.charm.cluster.database_provides.update_relation_data.assert_not_called()

        # fails because not leader
        self.harness.set_leader(False)
        self.harness.charm.cluster.update_config_server_db(mock.Mock())
        self.harness.charm.cluster.database_provides.update_relation_data.assert_not_called()
