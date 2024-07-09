#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest

from ..helpers import find_unit
from ..sharding_tests.helpers import deploy_cluster_components, integrate_cluster
from ..sharding_tests.writes_helpers import (
    SHARD_ONE_DB_NAME,
    SHARD_TWO_DB_NAME,
    count_shard_writes,
    stop_continous_writes,
)

MONGOD_SERVICE = "snap.charmed-mongodb.mongod.service"
MONGOS_SERVICE = "snap.charmed-mongodb.mongos.service"
SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
CONFIG_SERVER_APP_NAME = "config-server"
SHARD_COMPONENTS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME]
CLUSTER_COMPONENTS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME, CONFIG_SERVER_APP_NAME]
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
TIMEOUT = 15 * 60
MEDIAN_REELECTION_TIME = 12


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build deploy, and integrate, a sharded cluster.

    TODO: When upgrades are supported, deploy with most recent revision (6/stable when possible,
    but 6/edge as soon as available)
    """
    num_units_cluster_config = {
        CONFIG_SERVER_APP_NAME: 3,
        SHARD_ONE_APP_NAME: 3,
        SHARD_TWO_APP_NAME: 1,
    }
    await deploy_cluster_components(ops_test, num_units_cluster_config)

    await ops_test.model.wait_for_idle(
        apps=CLUSTER_COMPONENTS, idle_period=20, timeout=TIMEOUT, raise_on_blocked=False
    )
    await integrate_cluster(ops_test)
    await ops_test.model.wait_for_idle(
        apps=CLUSTER_COMPONENTS, status="active", idle_period=20, timeout=TIMEOUT
    )


@pytest.mark.skip("re-enable these tests once upgrades are available on charmhub")
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_rollback_on_config_server(
    ops_test: OpsTest, continuous_writes_to_shard_one, continuous_writes_to_shard_two
) -> None:
    """Verify that the config-server can safely rollback without losing writes."""
    new_charm = await ops_test.build_charm(".")
    config_server_unit = await find_unit(ops_test, leader=True, app_name=CONFIG_SERVER_APP_NAME)
    action = await config_server_unit.run_action("pre-upgrade-check")
    await action.wait()
    assert action.status == "completed", "pre-upgrade-check failed, expected to succeed."

    await ops_test.model.applications[CONFIG_SERVER_APP_NAME].refresh(path=new_charm)
    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], timeout=1000, idle_period=120
    )

    # instead of resuming upgrade refresh with the old version
    # TODO: instead of using new_charm - use the one deployed on charmhub - cannot do this until
    # the newest revision is published
    await ops_test.model.applications[CONFIG_SERVER_APP_NAME].refresh(path=new_charm)

    # verify no writes were skipped during upgrade/rollback process
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
        shard_one_actual_writes == shard_one_expected_writes["number"]
    ), "continuous writes to shard one failed during upgrade"
    assert (
        shard_two_actual_writes == shard_two_expected_writes["number"]
    ), "continuous writes to shard two failed during upgrade"

    # after all shards have upgraded, verify that the balancer has been turned back on
    # TODO implement this check once we have implemented the post-cluster-upgrade code DPE-4143


@pytest.mark.skip("re-enable these tests once upgrades are available on charmhub")
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_rollback_on_shard_and_config_server(
    ops_test: OpsTest, continuous_writes_to_shard_one, continuous_writes_to_shard_two
) -> None:
    """Verify that a config-server and shard can safely rollback without losing writes."""
    new_charm = await ops_test.build_charm(".")
    await run_upgrade_sequence(ops_test, CONFIG_SERVER_APP_NAME, new_charm)

    shard_unit = await find_unit(ops_test, leader=True, app_name=SHARD_ONE_APP_NAME)
    action = await shard_unit.run_action("pre-upgrade-check")
    await action.wait()
    assert action.status == "completed", "pre-upgrade-check failed, expected to succeed."

    # instead of resuming upgrade refresh with the old version
    # TODO: instead of using new_charm - use the one deployed on charmhub - cannot do this until
    # the newest revision is published
    await ops_test.model.applications[SHARD_ONE_APP_NAME].refresh(path=new_charm)
    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], timeout=1000, idle_period=120
    )

    # TODO: instead of using new_charm - use the one deployed on charmhub - cannot do this until
    # the newest revision is published
    await run_upgrade_sequence(ops_test, CONFIG_SERVER_APP_NAME, new_charm)

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
        shard_one_actual_writes == shard_one_expected_writes["number"]
    ), "continuous writes to shard one failed during upgrade"
    assert (
        shard_two_actual_writes == shard_two_expected_writes["number"]
    ), "continuous writes to shard two failed during upgrade"

    # after all shards have upgraded, verify that the balancer has been turned back on
    # TODO implement this check once we have implemented the post-cluster-upgrade code DPE-4143


async def run_upgrade_sequence(ops_test: OpsTest, app_name: str, new_charm) -> None:
    """Runs the upgrade sequence on a given app."""
    leader_unit = await find_unit(ops_test, leader=True, app_name=app_name)
    action = await leader_unit.run_action("pre-upgrade-check")
    await action.wait()
    assert action.status == "completed", "pre-upgrade-check failed, expected to succeed."

    await ops_test.model.applications[app_name].refresh(path=new_charm)
    await ops_test.model.wait_for_idle(apps=[app_name], timeout=1000, idle_period=120)

    action = await leader_unit.run_action("resume-upgrade")
    await action.wait()
    assert action.status == "completed", "resume-upgrade failed, expected to succeed."

    await ops_test.model.wait_for_idle(apps=[app_name], timeout=1000, idle_period=120)
