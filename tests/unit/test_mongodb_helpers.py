# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest import mock

from charms.mongodb.v1.helpers import get_mongod_args


class TestMongoDBHelpers(unittest.TestCase):
    def test_get_mongod_args(self):
        service_args_auth = [
            "--bind_ip_all",
            "--replSet=my_repl_set",
            "--dbpath=/var/snap/charmed-mongodb/common/var/lib/mongodb",
            "--port=27017",
            "--setParameter",
            "processUmask=037",
            "--logpath=/var/snap/charmed-mongodb/common/var/log/mongodb/mongodb.log",
            "--auditDestination=file",
            "--auditFormat=JSON",
            "--auth",
            "--clusterAuthMode=keyFile",
            "--keyFile=/var/snap/charmed-mongodb/current/etc/mongod/keyFile",
        ]

        config = mock.Mock()
        config.replset = "my_repl_set"
        config.tls_external = False
        config.tls_internal = False

        self.assertEqual(
            get_mongod_args(config, auth=True, snap_install=True).split(),
            service_args_auth,
        )

        service_args = [
            # bind to localhost and external interfaces
            "--bind_ip_all",
            # part of replicaset
            "--replSet=my_repl_set",
            "--dbpath=/var/snap/charmed-mongodb/common/var/lib/mongodb",
            "--port=27017",
            "--setParameter",
            "processUmask=037",
            "--logpath=/var/snap/charmed-mongodb/common/var/log/mongodb/mongodb.log",
            "--auditDestination=file",
            "--auditFormat=JSON",
        ]

        self.assertEqual(
            get_mongod_args(config, auth=False, snap_install=True).split(),
            service_args,
        )

        service_args = [
            # bind to localhost and external interfaces
            "--bind_ip_all",
            # part of replicaset
            "--replSet=my_repl_set",
            "--dbpath=/var/lib/mongodb",
            "--port=27017",
            "--setParameter",
            "processUmask=037",
            "--logpath=/var/log/mongodb/mongodb.log",
            "--auditDestination=file",
            "--auditFormat=JSON",
        ]

        self.assertEqual(
            get_mongod_args(config, auth=False, snap_install=False).split(),
            service_args,
        )
