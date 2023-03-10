# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest import mock

from charms.mongodb.v0.helpers import get_mongod_args


class TestMongoDBHelpers(unittest.TestCase):
    def test_get_mongod_args(self):
        service_args_auth = " ".join(
            [
                "--bind_ip_all",
                "--replSet=my_repl_set",
                "--dbpath=/var/snap/charmed-mongodb/common/var/lib/mongodb",
                "--auth",
                "--clusterAuthMode=keyFile",
                "--keyFile=/var/snap/charmed-mongodb/current/etc/mongod/keyFile",
                "\n",
            ]
        )

        config = mock.Mock()
        config.replset = "my_repl_set"
        config.tls_external = False
        config.tls_internal = False

        self.assertEqual(
            get_mongod_args(config, auth=True, snap_install=True),
            service_args_auth,
        )

        service_args = " ".join(
            [
                # bind to localhost and external interfaces
                "--bind_ip_all",
                # part of replicaset
                "--replSet=my_repl_set",
                "--dbpath=/var/snap/charmed-mongodb/common/var/lib/mongodb",
                "--clusterAuthMode=keyFile",
                "--keyFile=/var/snap/charmed-mongodb/current/etc/mongod/keyFile",
                "\n",
            ]
        )

        self.assertEqual(
            get_mongod_args(config, auth=False, snap_install=True),
            service_args,
        )
