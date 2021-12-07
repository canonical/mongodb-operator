# Copyright 2021 Canonical
# See LICENSE file for licensing details.

import unittest
from unittest import mock
from unittest.mock import call, mock_open, patch
from tests.helpers import patch_network_get
from charm import MongodbOperatorCharm
from ops.model import ActiveStatus, MaintenanceStatus
from ops.testing import Harness

MONGO_CONF_ORIG = """# mongod.conf

# for documentation of all options, see:
#   http://docs.mongodb.org/manual/reference/configuration-options/

# Where and how to store data.
storage:
  dbPath: /var/lib/mongodb
  journal:
    enabled: true
#  engine:
#  wiredTiger:

# where to write logging data.
systemLog:
  destination: file
  logAppend: true
  path: /var/log/mongodb/mongod.log

# network interfaces
net:
  port: 27017
  bindIp: 127.0.0.1


# how the process runs
processManagement:
  timeZoneInfo: /usr/share/zoneinfo

#security:

#operationProfiling:

#replication:

#sharding:

## Enterprise-Only Options:

#auditLog:

#snmp:
"""

MONGO_CONF_ARGS = [
    "net",
    ":",
    "\n",
    "  ",
    "bindIp",
    ":",
    " ",
    "localhost,1.1.1.1",
    "\n",
    "  ",
    "port",
    ":",
    " ",
    "27017",
    "\n",
    "processManagement",
    ":",
    "\n",
    "  ",
    "timeZoneInfo",
    ":",
    " ",
    "/usr/share/zoneinfo",
    "\n",
    "replication",
    ":",
    "\n",
    "  ",
    "replSetName",
    ":",
    " ",
    "rs0",
    "\n",
    "storage",
    ":",
    "\n",
    "  ",
    "dbPath",
    ":",
    " ",
    "/var/lib/mongodb",
    "\n",
    "  ",
    "journal",
    ":",
    "\n",
    "    ",
    "enabled",
    ":",
    " ",
    "true",
    "\n",
    "systemLog",
    ":",
    "\n",
    "  ",
    "destination",
    ":",
    " ",
    "file",
    "\n",
    "  ",
    "logAppend",
    ":",
    " ",
    "true",
    "\n",
    "  ",
    "path",
    ":",
    " ",
    "/var/log/mongodb/mongod.log",
    "\n",
]


class TestCharm(unittest.TestCase):
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.peer_rel_id = self.harness.add_relation("mongodb", "mongodb")
        # self.harness.begin_with_initial_hooks()

    @mock.patch("charm.MongodbOperatorCharm._add_mongodb_org_repository")
    @mock.patch("charm.MongodbOperatorCharm._install_apt_packages")
    def test_mongoDB_install(self, _add, _install):
        self.harness.charm.on.install.emit()
        self.assertEqual(self.harness.charm.unit.status, MaintenanceStatus("installing MongoDB"))
        _install.assert_called_once()
        _add.assert_called_with(["mongodb-org"])

    @patch_network_get(private_address="1.1.1.1")
    def test_on_config_changed(self):
        open_mock = mock_open(read_data=MONGO_CONF_ORIG)
        with patch("builtins.open", open_mock, create=True):
            self.harness.charm.on.config_changed.emit()

        # TODO change expected output based on config options, (once config options are implemented)
        open_mock.assert_called_with("/etc/mongod.conf", "w")
        open_mock.return_value.write.assert_has_calls([mock.call(arg) for arg in MONGO_CONF_ARGS])
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch_network_get(private_address="1.1.1.1")
    @mock.patch("mongoserver.MongoDB.is_ready")
    @mock.patch("mongoserver.MongoDB.initialize_replica_set")
    @mock.patch("charm.check_call")
    @mock.patch("charm.service_resume")
    @mock.patch("charm.service_restart")
    def test_on_start(
        self, service_restart, service_resume, _call, initialize_replica_set, is_ready
    ):
        self.harness.set_leader(True)
        is_ready.return_value = True

        self.harness.charm.on.start.emit()

        # Make sure the port is opened
        self.assertEqual(_call.call_args_list, [call(["open-port", "27017/TCP"])])

        # Check if mongod is started
        service_resume.assert_called_with("mongod.service")
        service_restart.assert_called_with("mongod.service")

        # Check if mongod is ready
        is_ready.assert_called()

        # Check that replica set is initialized with correct IP
        initialize_replica_set.assert_called_with(["1.1.1.1"])

        # Ensure we set an ActiveStatus for the charm
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus("MongoDB started"))

    @mock.patch("charm.check_call")
    def test_set_port(self, _call):
        self.harness.charm._open_port_tcp(27017)
        # Make sure the port is opened and the service is started
        self.assertEqual(_call.call_args_list, [call(["open-port", "27017/TCP"])])
