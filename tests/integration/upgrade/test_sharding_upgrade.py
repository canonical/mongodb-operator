#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from ..sharding_tests.writes_helpers import (
    continuous_writes_to_shard_one,
    continuous_writes_to_shard_two,
)

from ..sharding_tests.helpers import deploy_cluster_components, integrate_cluster

from ..ha_tests import helpers as ha_helpers
from ..helpers import unit_hostname, find_unit

MONGOD_SERVICE = "snap.charmed-mongodb.mongod.service"
MONGOS_SERVICE = "snap.charmed-mongodb.mongos.service"
SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
CONFIG_SERVER_APP_NAME = "config-server"
CLUSTER_COMPONENTS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME, CONFIG_SERVER_APP_NAME]
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
TIMEOUT = 15 * 60

# TODO continuous writes to both shards


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build deploy, and integrate, a sharded cluster."""
    await deploy_cluster_components(ops_test)

    await ops_test.model.wait_for_idle(
        apps=CLUSTER_COMPONENTS, idle_period=20, timeout=TIMEOUT, raise_on_blocked=False
    )


async def test_pre_upgrade_check_failure(ops_test: OpsTest) -> None:
    """Verify that the pre-upgrade check fails if there is a problem with one of the shards."""
    # disable network on all shard replicas prior to integration. This prevents the shard from
    # joining the cluster
    config_server_unit = await find_unit(ops_test, leader=True, app_name=CONFIG_SERVER_APP_NAME)
    for shard_unit in ops_test.model.applications[SHARD_ONE_APP_NAME].units:
        ha_helpers.cut_network_from_unit(await unit_hostname(ops_test, shard_unit.name))

    await integrate_cluster(ops_test)
    await ops_test.model.wait_for_idle(
        apps=CLUSTER_COMPONENTS, idle_period=20, timeout=TIMEOUT, raise_on_blocked=False
    )

    action = await config_server_unit.run_action("pre-upgrade-check")
    await action.wait()
    assert action.status == "failed", "pre-upgrade-check succeeded, expected to fail."

    # re-enable network on sharded cluster and wait for idle active
    for shard_unit in ops_test.model.applications[SHARD_ONE_APP_NAME].units:
        ha_helpers.restore_network_for_unit(await unit_hostname(ops_test, shard_unit.name))

    await ops_test.model.wait_for_idle(
        apps=CLUSTER_COMPONENTS, idle_period=20, timeout=TIMEOUT, raise_on_blocked=False
    )

    # enable tls on only the shard and not the config-server. This prevents communication from the
    # shard and config-server
    # TODO
    # disable tls on the shard and verify that the cluster is in the healthy state
    # TODO


async def test_pre_upgrade_check_success(ops_test: OpsTest) -> None:
    """TODO"""


async def test_upgrade(
    ops_test: OpsTest, continuous_writes_to_shard_one, continuous_writes_to_shard_two
) -> None:
    """TODO"""

    # before upgrading shard, verify that the balancer hasn't been turned back on

    # after all shards have upgraded, verify that the balancer has been turned back on
    # TODO implement this check once we have implemented the post-cluster-upgrade code
