#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pytest_operator.plugin import OpsTest

from ..ha_tests import helpers as ha_helpers
from ..helpers import check_or_scale_app, find_unit, get_app_name

logger = logging.getLogger(__name__)


MEDIAN_REELECTION_TIME = 12


@pytest.fixture()
async def continuous_writes(ops_test: OpsTest):
    """Starts continuous write operations to MongoDB for test and clears writes at end of test."""
    await ha_helpers.start_continous_writes(ops_test, 1)
    yield
    await ha_helpers.clear_db_writes(ops_test)


@pytest.mark.skip(reason="Must wait for stable channel to support upgrades before testing")
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for testing. Hence check if there
    # is a pre-existing cluster.
    app_name = await get_app_name(ops_test)
    if app_name:
        return await check_or_scale_app(ops_test, app_name)

    await ops_test.model.deploy("mongodb", channel="stable", num_units=3)
    await ops_test.model.wait_for_idle(
        apps=["mongodb"], status="active", timeout=1000, idle_period=120
    )


@pytest.mark.skip(reason="Must wait for stable channel to support upgrades before testing")
async def test_upgrade(ops_test: OpsTest, continuous_writes) -> None:
    """Verifies that the upgrade can run successfully."""
    app_name = await get_app_name(ops_test)
    leader_unit = await find_unit(ops_test, leader=True, app_name=app_name)
    logger.info("Calling pre-upgrade-check")
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()

    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, idle_period=120
    )

    new_charm = await ops_test.build_charm(".")
    app_name = await get_app_name(ops_test)
    await ops_test.model.applications[app_name].refresh(path=new_charm)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, idle_period=120
    )

    # verify that the no writes were skipped
    total_expected_writes = await ha_helpers.stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await ha_helpers.count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.skip(reason="Must wait for stable channel to support upgrades before testing")
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