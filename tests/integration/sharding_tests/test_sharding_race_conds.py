#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import generate_mongodb_client, has_correct_shards

SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
SHARD_THREE_APP_NAME = "shard-three"
SHARD_APPS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME]
CONFIG_SERVER_APP_NAME = "config-server-one"
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
MONGODB_KEYFILE_PATH = "/var/snap/charmed-mongodb/current/etc/mongod/keyFile"

TIMEOUT = 60 * 30


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy a sharded cluster."""
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(
        my_charm,
        num_units=2,
        config={"role": "config-server"},
        application_name=CONFIG_SERVER_APP_NAME,
    )
    await ops_test.model.deploy(
        my_charm, num_units=2, config={"role": "shard"}, application_name=SHARD_ONE_APP_NAME
    )
    await ops_test.model.deploy(
        my_charm, num_units=2, config={"role": "shard"}, application_name=SHARD_TWO_APP_NAME
    )
    await ops_test.model.deploy(
        my_charm, num_units=2, config={"role": "shard"}, application_name=SHARD_THREE_APP_NAME
    )


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_immediate_relate(ops_test: OpsTest) -> None:
    """Tests the immediate integration of cluster components works without error."""
    await ops_test.model.integrate(
        f"{SHARD_ONE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )
    await ops_test.model.integrate(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )
    await ops_test.model.integrate(
        f"{SHARD_THREE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    # This test mainly fails on GH runners due to to low timeout (still 30 mins) +
    # update-status-hook-interval to be too high.
    # Safe to use here because `wait_for_idle` cannot raise an error.
    async with ops_test.fast_forward("3m"):
        await ops_test.model.wait_for_idle(
            apps=[
                CONFIG_SERVER_APP_NAME,
                SHARD_ONE_APP_NAME,
                SHARD_TWO_APP_NAME,
                SHARD_THREE_APP_NAME,
            ],
            idle_period=20,
            status="active",
            timeout=TIMEOUT,
            raise_on_error=False,
        )

    mongos_client = await generate_mongodb_client(
        ops_test, app_name=CONFIG_SERVER_APP_NAME, mongos=True
    )

    # verify sharded cluster config
    assert has_correct_shards(
        mongos_client,
        expected_shards=[SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME, SHARD_THREE_APP_NAME],
    ), "Config server did not process config properly"
