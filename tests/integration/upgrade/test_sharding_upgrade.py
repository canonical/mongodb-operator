#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import time
import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from ..sharding_tests.writes_helpers import (
    continuous_writes_to_shard_one,
    continuous_writes_to_shard_two,
    stop_continous_writes,
)

from ..sharding_tests.helpers import deploy_cluster_components, integrate_cluster

from ..ha_tests import helpers as ha_helpers
from ..helpers import unit_hostname, find_unit, get_unit_ip

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

# TODO continuous writes to both shards


# @pytest.mark.group(1)
# @pytest.mark.abort_on_fail
# async def test_build_and_deploy(ops_test: OpsTest) -> None:
#     """Build deploy, and integrate, a sharded cluster.

#     TODO: When upgrades are supported, deploy with most recent revision (6/stable when possible,
#     but 6/edge as soon as available)
#     """

#     await deploy_cluster_components(ops_test)

#     await ops_test.model.wait_for_idle(
#         apps=CLUSTER_COMPONENTS, idle_period=20, timeout=TIMEOUT, raise_on_blocked=False
#     )
#     await integrate_cluster(ops_test)
#     await ops_test.model.wait_for_idle(
#         apps=CLUSTER_COMPONENTS, status="active", idle_period=20, timeout=TIMEOUT
#     )


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_pre_upgrade_check_failure(ops_test: OpsTest) -> None:
    """Verify that the pre-upgrade check fails if there is a problem with one of the shards."""

    # Disable network on a replicas prior to integration.
    # After disabling the network, it will be impossible to retrieve the hostname, and ip address,
    # so save them before disabling, so they can used to re-enable the network.
    shard_unit = ops_test.model.applications[SHARD_ONE_APP_NAME].units[0]
    shard_one_host_name = await unit_hostname(ops_test, shard_unit.name)
    ha_helpers.cut_network_from_unit(shard_one_host_name)

    config_server_unit = await find_unit(ops_test, leader=True, app_name=CONFIG_SERVER_APP_NAME)
    action = await config_server_unit.run_action("pre-upgrade-check")
    await action.wait()
    assert action.status == "failed", "pre-upgrade-check succeeded, expected to fail."

    # re-enable network on sharded cluster and wait for idle active
    ha_helpers.restore_network_for_unit(shard_one_host_name)

    async with ops_test.fast_forward():
        # sleep for twice the median election time
        time.sleep(MEDIAN_REELECTION_TIME * 2)

        await ops_test.model.wait_for_idle(
            apps=CLUSTER_COMPONENTS,
            idle_period=20,
            status="active",
            timeout=TIMEOUT,
            raise_on_blocked=False,
        )

    # TODO Future PR: Add more cases for failing pre-upgrade-check


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_pre_upgrade_check_success(ops_test: OpsTest) -> None:
    """Verify that the pre-upgrade-check succeeds on config-server"""
    config_server_unit = await find_unit(ops_test, leader=True, app_name=CONFIG_SERVER_APP_NAME)
    action = await config_server_unit.run_action("pre-upgrade-check")
    await action.wait()
    assert action.status == "success", "pre-upgrade-check failed, expected to suceed."


# @pytest.mark.skip("re-enable these tests once upgrades are available on charmhub")
# @pytest.mark.group(1)
# @pytest.mark.abort_on_fail
# async def test_upgrade(
#     ops_test: OpsTest, continuous_writes_to_shard_one, continuous_writes_to_shard_two
# ) -> None:
#     """Verify that the sharded cluster can be safely upgraded without losing writes."""
#     # scale up shard 2 since it only has one relplica and when it restarts due to an upgrade it
#     # could lose some writes.
#     await ops_test.model.applications[SHARD_TWO_APP_NAME].add_unit(count=1)

#     await ops_test.model.wait_for_idle(
#         apps=CLUSTER_COMPONENTS, idle_period=20, timeout=TIMEOUT, raise_on_blocked=False
#     )

#     config_server_unit = await find_unit(ops_test, leader=True, app_name=CONFIG_SERVER_APP_NAME)
#     action = await config_server_unit.run_action("pre-upgrade-check")
#     await action.wait()
#     assert action.status == "success", "pre-upgrade-check failed, expected to suceed."

#     new_charm = await ops_test.build_charm(".")
#     await ops_test.model.applications[CONFIG_SERVER_APP_NAME].refresh(path=new_charm)
#     await ops_test.model.wait_for_idle(
#         apps=[CONFIG_SERVER_APP_NAME], timeout=1000, idle_period=120
#     )

#     # TODO before upgrading shard, verify that the balancer hasn't been turned back on

#     for shard_app_name in SHARD_COMPONENTS:
#         shard_leader_unit = await find_unit(ops_test, leader=True, app_name=shard_app_name)
#         action = await shard_leader_unit.run_action("pre-upgrade-check")
#         await action.wait()
#         assert action.status == "success", "pre-upgrade-check failed, expected to suceed."
#         await ops_test.model.applications[CONFIG_SERVER_APP_NAME].refresh(path=new_charm)
#         await ops_test.model.wait_for_idle(
#             apps=[CONFIG_SERVER_APP_NAME], timeout=1000, idle_period=120
#         )

#     # TODO verify that the no writes were skipped
#     await stop_continous_writes(ops_test, config_server_name=CONFIG_SERVER_APP_NAME)

#     total_expected_writes = await ha_helpers.stop_continous_writes(ops_test, app_name=app_name)
#     actual_writes = await ha_helpers.count_writes(ops_test, app_name=app_name)
#     assert total_expected_writes["number"] == actual_writes

#     # after all shards have upgraded, verify that the balancer has been turned back on
#     # TODO implement this check once we have implemented the post-cluster-upgrade code
