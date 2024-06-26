# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest import mock
from unittest.mock import patch

from ops.testing import Harness

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

    def test_are_charm_units_all_active_or_waiting_for_upgrade(self) -> None:
        """Verify that status handler returns the correct status."""
        # case 1: all juju units are ready for upgrade
        goal_state = {"units": {"unit_0": {"status": "active"}}}
        run_mock = mock.Mock()
        run_mock._run.return_value = goal_state
        self.harness.charm.model._backend = run_mock

        assert self.harness.charm.status.are_charm_units_all_active_or_waiting_for_upgrade()

        # case 2: not all juju units are ready for upgrade
        goal_state = {"units": {"unit_0": {"status": "active"}, "unit_1": {"status": "blocked"}}}
        run_mock = mock.Mock()
        run_mock._run.return_value = goal_state
        self.harness.charm.model._backend = run_mock

        assert not self.harness.charm.status.are_charm_units_all_active_or_waiting_for_upgrade()
