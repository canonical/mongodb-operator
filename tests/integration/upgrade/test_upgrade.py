#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os

import pytest
from pytest_operator.plugin import OpsTest

from ..helpers import check_or_scale_app, find_unit, get_app_name

logger = logging.getLogger(__name__)


MEDIAN_REELECTION_TIME = 12


@pytest.mark.group(1)
@pytest.mark.skipif(
    os.environ.get("PYTEST_SKIP_DEPLOY", False),
    reason="skipping deploy, model expected to be provided.",
)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for testing. Hence check if there
    # is a pre-existing cluster.
    app_name = await get_app_name(ops_test)
    if app_name:
        return await check_or_scale_app(ops_test, app_name)

    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=3)
    await ops_test.model.wait_for_idle()


@pytest.mark.group(1)
async def test_preflight_check(ops_test: OpsTest) -> None:
    """Verifies that the preflight check can run successfully."""
    app_name = await get_app_name(ops_test)
    leader_unit = await find_unit(ops_test, leader=True, app_name=app_name)
    logger.info("Calling pre-upgrade-check")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()

    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, idle_period=120
    )
