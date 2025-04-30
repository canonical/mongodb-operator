# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest import mock
from unittest.mock import patch

from ops.model import ActiveStatus, BlockedStatus, StatusBase, WaitingStatus
from ops.testing import Harness
from parameterized import parameterized
from single_kernel_mongo.config.literals import Scope

from charm import MongoDBVMCharm

CHARM_VERSION = "127"


class TestCharm(unittest.TestCase):
    @patch("single_kernel_mongo.managers.mongodb_operator.get_charm_revision")
    def setUp(self, get_charm_revision):
        get_charm_revision.return_value = CHARM_VERSION
        self.harness = Harness(MongoDBVMCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @parameterized.expand(
        [
            [
                False,
                True,
                None,
                BlockedStatus(
                    "Relation to mongos not supported, config role must be config-server"
                ),
            ],
            [
                False,
                False,
                None,
                BlockedStatus(
                    "Relation to mongos not supported, config role must be config-server"
                ),
            ],
            [
                True,
                False,
                None,
                BlockedStatus(
                    "Relation to s3-integrator is not supported, config role must be config-server"
                ),
            ],
            [True, True, None, None],
            [True, True, ActiveStatus(), ActiveStatus()],
            [True, True, BlockedStatus(""), BlockedStatus("")],
            [True, True, WaitingStatus(""), WaitingStatus("")],
        ]
    )
    def test_get_invalid_integration_status(
        self,
        mongos_integration: bool,
        valid_s3_integration: bool,
        mismatched_revision_status: StatusBase | None,
        expected_status: StatusBase | None,
    ):
        """Tests different cases of statuses for get_invalid_integration_status."""
        get_mismatched_revision_mock = mock.Mock()
        get_mismatched_revision_mock.return_value = mismatched_revision_status

        mongos_integration_mock = mock.Mock()
        mongos_integration_mock.return_value = mongos_integration

        valid_s3_integration_mock = mock.Mock()
        valid_s3_integration_mock.return_value = valid_s3_integration

        self.harness.charm.operator.cluster_version_checker.get_cluster_mismatched_revision_status = (
            get_mismatched_revision_mock
        )
        self.harness.charm.operator.cluster_manager.is_valid_mongos_integration = (
            mongos_integration_mock
        )
        self.harness.charm.operator.backup_manager.is_valid_s3_integration = (
            valid_s3_integration_mock
        )

        statuses = self.harness.charm.operator.compute_statuses(scope=Scope.UNIT)
        status = next(iter(statuses), None)

        assert status.status == expected_status or ActiveStatus("")
