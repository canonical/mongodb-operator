#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import helpers
import pytest
from pytest_operator.plugin import OpsTest


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for HA testing. Hence check if there
    # is a pre-existing cluster.
    if await helpers.app_name(ops_test):
        return

    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=3)
    await ops_test.model.wait_for_idle()


@pytest.mark.abort_on_fail
async def test_install_pbm(ops_test: OpsTest) -> None:
    """Verifies that pbm snap was installed."""
    app = await helpers.app_name(ops_test)
    unit = ops_test.model.applications[app].units[0]
    pbm_cmd = f"run --unit {unit.name} percona-backup-mongodb"
    return_code, _, _ = await ops_test.juju(*pbm_cmd.split())
    assert return_code == 0, "percona-backup-mongodb not installed"
