#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
# TODO: Move this back to `test_sharding_rollback.py` when
# https://github.com/juju/juju/issues/19631 is fixed.
import asyncio

import pytest
from pytest_operator.plugin import OpsTest

from ..helpers import DEPLOYMENT_TIMEOUT, wait_for_mongodb_units_blocked
from ..sharding_tests.helpers import deploy_cluster_components, integrate_cluster
from ..sharding_tests.writes_helpers import (
    SHARD_ONE_DB_NAME,
    SHARD_TWO_DB_NAME,
    count_shard_writes,
    stop_continous_writes,
)
from .test_sharding_rollback import refresh_with_juju, run_upgrade_sequence

SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
CONFIG_SERVER_APP_NAME = "config-server"
SHARD_COMPONENTS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME]
CLUSTER_COMPONENTS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME, CONFIG_SERVER_APP_NAME]


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build deploy, and integrate, a sharded cluster."""
    num_units_cluster_config = {
        CONFIG_SERVER_APP_NAME: 3,
        SHARD_ONE_APP_NAME: 3,
        SHARD_TWO_APP_NAME: 1,
    }
    await deploy_cluster_components(ops_test, num_units_cluster_config, channel="6/edge")

    await ops_test.model.wait_for_idle(
        apps=CLUSTER_COMPONENTS,
        idle_period=20,
        timeout=DEPLOYMENT_TIMEOUT,
        raise_on_blocked=False,
    )
    await integrate_cluster(ops_test)
    await ops_test.model.wait_for_idle(
        apps=CLUSTER_COMPONENTS,
        status="active",
        idle_period=20,
        timeout=DEPLOYMENT_TIMEOUT,
    )


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_rollback_on_shard_and_config_server(
    ops_test: OpsTest, continuous_writes_to_shard_one, continuous_writes_to_shard_two
) -> None:
    """Verify that a config-server and shard can safely rollback without losing writes."""
    new_charm = await ops_test.build_charm(".")
    await run_upgrade_sequence(ops_test, CONFIG_SERVER_APP_NAME, new_charm=new_charm)

    with open("charm_version", mode="r") as fd:
        revision = fd.read().strip()

    # Wait for statuses to settle down
    asyncio.gather(
        wait_for_mongodb_units_blocked(ops_test, SHARD_ONE_APP_NAME),
        wait_for_mongodb_units_blocked(ops_test, SHARD_TWO_APP_NAME),
        ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME],
            timeout=1000,
            idle_period=20,
            status=f"Waiting for shards to upgrade/downgrade to revision {revision}-locally built.",
        ),
    )

    await run_upgrade_sequence(ops_test, SHARD_ONE_APP_NAME, new_charm=new_charm)

    # Wait for statuses to settle down
    asyncio.gather(
        wait_for_mongodb_units_blocked(ops_test, SHARD_TWO_APP_NAME),
        ops_test.model.wait_for_idle(apps=[SHARD_ONE_APP_NAME], timeout=1000, idle_period=20),
        ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME],
            timeout=1000,
            idle_period=20,
            status=f"Waiting for shards to upgrade/downgrade to revision {revision}-locally built.",
        ),
    )

    await refresh_with_juju(ops_test, CONFIG_SERVER_APP_NAME, channel="6/edge")

    # verify no writes were skipped during upgrade process
    shard_one_expected_writes = await stop_continous_writes(
        ops_test,
        config_server_name=CONFIG_SERVER_APP_NAME,
        db_name=SHARD_ONE_DB_NAME,
    )
    shard_two_expected_writes = await stop_continous_writes(
        ops_test,
        config_server_name=CONFIG_SERVER_APP_NAME,
        db_name=SHARD_TWO_DB_NAME,
    )

    shard_one_actual_writes = await count_shard_writes(
        ops_test, CONFIG_SERVER_APP_NAME, SHARD_ONE_DB_NAME
    )
    shard_two_actual_writes = await count_shard_writes(
        ops_test, CONFIG_SERVER_APP_NAME, SHARD_TWO_DB_NAME
    )
    assert (
        shard_one_actual_writes >= shard_one_expected_writes["number"]
    ), "continuous writes to shard one failed during upgrade"
    assert (
        shard_two_actual_writes >= shard_two_expected_writes["number"]
    ), "continuous writes to shard two failed during upgrade"

    # after all shards have upgraded, verify that the balancer has been turned back on
    # TODO implement this check once we have implemented the post-cluster-upgrade code DPE-4143
