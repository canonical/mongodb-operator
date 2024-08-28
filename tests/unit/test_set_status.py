# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest import mock
from unittest.mock import patch

from ops.model import ActiveStatus, BlockedStatus, StatusBase, WaitingStatus
from ops.testing import Harness
from parameterized import parameterized

from charm import MongodbOperatorCharm

from .helpers import patch_network_get

CHARM_VERSION = 123


class TestCharm(unittest.TestCase):
    @patch("charm.get_charm_revision")
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self, get_charm_revision):
        get_charm_revision.return_value = CHARM_VERSION
        self.harness = Harness(MongodbOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_are_all_units_ready_for_upgrade(self) -> None:
        """Verify that status handler returns the correct status."""
        # case 1: all juju units are ready for upgrade
        goal_state = {"units": {"unit_0": {"status": "active"}}}
        get_mismatched_revsion = mock.Mock()
        get_mismatched_revsion.return_value = None
        run_mock = mock.Mock()
        run_mock._run.return_value = goal_state
        self.harness.charm.model._backend = run_mock
        self.harness.charm.get_cluster_mismatched_revision_status = get_mismatched_revsion

        assert self.harness.charm.status.are_all_units_ready_for_upgrade()

        # case 2: not all juju units are ready for upgrade
        goal_state = {"units": {"unit_0": {"status": "active"}, "unit_1": {"status": "blocked"}}}
        run_mock = mock.Mock()
        run_mock._run.return_value = goal_state
        self.harness.charm.model._backend = run_mock

        assert not self.harness.charm.status.are_all_units_ready_for_upgrade()

    @parameterized.expand(
        [
            [ActiveStatus(), True],
            [BlockedStatus("is not up-to date with config-server"), True],
            [BlockedStatus("Wrong status"), False],
            [WaitingStatus("tests status"), False],
        ],
    )
    def test_is_unit_status_ready_for_upgrade(self, status: StatusBase, expected: bool) -> None:
        """Tests different cases of statuses for is_unit_status_ready_for_upgrade."""
        self.harness.charm.unit.status = status

        assert self.harness.charm.status.is_unit_status_ready_for_upgrade() == expected

    @parameterized.expand(
        [
            [BlockedStatus("Invalid"), ActiveStatus(), ActiveStatus(), ActiveStatus(), 0],
            [WaitingStatus("Waiting"), ActiveStatus(), ActiveStatus(), ActiveStatus(), 0],
            [ActiveStatus(), BlockedStatus("Invalid"), ActiveStatus(), ActiveStatus(), 1],
            [ActiveStatus(), WaitingStatus("Waiting"), ActiveStatus(), ActiveStatus(), 1],
            [ActiveStatus(), None, BlockedStatus("Invalid"), ActiveStatus(), 2],
            [ActiveStatus(), None, WaitingStatus("Waiting"), ActiveStatus(), 2],
            [ActiveStatus(), None, None, BlockedStatus("Invalid"), 3],
            [ActiveStatus(), None, None, WaitingStatus("Waiting"), 3],
            [ActiveStatus(), None, None, None, 0],
            [ActiveStatus(), ActiveStatus(), ActiveStatus(), ActiveStatus(), 0],
        ]
    )
    def test_prioritize_status(
        self,
        mongodb_status: StatusBase,
        shard_status: StatusBase | None,
        config_server_status: StatusBase | None,
        pbm_status: StatusBase | None,
        expected_index: int,
    ):
        """Tests different cases of statuses for prioritize_status."""
        statuses = (mongodb_status, shard_status, config_server_status, pbm_status)
        assert self.harness.charm.status.prioritize_statuses(statuses) == statuses[expected_index]

    @parameterized.expand(
        [
            [
                False,
                True,
                ActiveStatus(),
                BlockedStatus(
                    "Relation to mongos not supported, config role must be config-server"
                ),
            ],
            [
                False,
                False,
                ActiveStatus(),
                BlockedStatus(
                    "Relation to mongos not supported, config role must be config-server"
                ),
            ],
            [
                True,
                False,
                ActiveStatus(),
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

        self.harness.charm.get_cluster_mismatched_revision_status = get_mismatched_revision_mock
        self.harness.charm.cluster.is_valid_mongos_integration = mongos_integration_mock
        self.harness.charm.backups.is_valid_s3_integration = valid_s3_integration_mock

        assert self.harness.charm.status.get_invalid_integration_status() == expected_status
