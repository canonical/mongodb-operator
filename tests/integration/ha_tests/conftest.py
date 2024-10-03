#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import pytest
from pytest_operator.plugin import OpsTest

from ..helpers import get_app_name
from .helpers import clear_db_writes, start_continous_writes, update_restart_delay

ORIGINAL_RESTART_DELAY = 5


@pytest.fixture
async def continuous_writes(ops_test: OpsTest):
    """Starts continuous write operations to MongoDB for test and clears writes at end of test."""
    await start_continous_writes(ops_test, 1)
    yield
    await clear_db_writes(ops_test)


@pytest.fixture
async def reset_restart_delay(ops_test: OpsTest):
    """Resets service file delay on all units."""
    yield
    app_name = await get_app_name(ops_test)
    for unit in ops_test.model.applications[app_name].units:
        await update_restart_delay(ops_test, unit, ORIGINAL_RESTART_DELAY)


@pytest.fixture(scope="module")
async def database_charm(ops_test: OpsTest):
    """Build the database charm."""
    charm = await ops_test.build_charm(".")
    return charm
