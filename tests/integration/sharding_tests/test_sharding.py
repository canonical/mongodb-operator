#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio

import pytest
from pytest_operator.plugin import OpsTest

from .helpers import generate_mongodb_client, verify_data_mongodb, write_data_to_mongodb

SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
SHARD_APPS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME]
CONFIG_SERVER_APP_NAME = "config-server-one"
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
MONGODB_KEYFILE_PATH = "/var/snap/charmed-mongodb/current/etc/mongod/keyFile"
# for now we have a large timeout due to the slow drainage of the `config.system.sessions`
# collection. More info here:
# https://stackoverflow.com/questions/77364840/mongodb-slow-chunk-migration-for-collection-config-system-sessions-with-remov
TIMEOUT = 30 * 60


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

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
            idle_period=20,
            raise_on_blocked=False,
            timeout=TIMEOUT,
        )

    # verify that Charmed MongoDB is blocked and reports incorrect credentials
    await asyncio.gather(
        ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME],
            status="active",
            idle_period=20,
            timeout=TIMEOUT,
        ),
        ops_test.model.wait_for_idle(
            apps=[SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
            status="blocked",
            idle_period=20,
            timeout=TIMEOUT,
        ),
    )

    # TODO Future PR: assert statuses for config-server
    for shard_app_name in SHARD_APPS:
        shard_unit = ops_test.model.applications[shard_app_name].units[0]
        assert shard_unit.workload_status_message == "missing relation to config server"


@pytest.mark.abort_on_fail
async def test_cluster_active(ops_test: OpsTest) -> None:
    """Tests the integration of cluster components works without error."""
    await ops_test.model.integrate(
        f"{SHARD_ONE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )
    await ops_test.model.integrate(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
            idle_period=20,
            status="active",
            timeout=TIMEOUT,
        )

    # TODO Future PR: assert statuses for config-server
    for shard_app_name in SHARD_APPS:
        shard_unit = ops_test.model.applications[shard_app_name].units[0]
        assert (
            shard_unit.workload_status_message
            == f"Shard connected to config-server: {CONFIG_SERVER_APP_NAME}"
        )


async def test_sharding(ops_test: OpsTest) -> None:
    """Tests writing data to mongos gets propagated to shards."""
    # write data to mongos on both shards.
    mongos_client = await generate_mongodb_client(
        ops_test, app_name=CONFIG_SERVER_APP_NAME, mongos=True
    )

    # write data to shard one
    write_data_to_mongodb(
        mongos_client,
        db_name="animals_database_1",
        coll_name="horses",
        content={"horse-breed": "unicorn", "real": True},
    )
    mongos_client.admin.command("movePrimary", "animals_database_1", to=SHARD_ONE_APP_NAME)

    # write data to shard two
    write_data_to_mongodb(
        mongos_client,
        db_name="animals_database_2",
        coll_name="horses",
        content={"horse-breed": "pegasus", "real": True},
    )
    mongos_client.admin.command("movePrimary", "animals_database_2", to=SHARD_TWO_APP_NAME)

    # log into shard 1 verify data
    shard_one_client = await generate_mongodb_client(
        ops_test, app_name=SHARD_ONE_APP_NAME, mongos=False
    )
    has_correct_data = verify_data_mongodb(
        shard_one_client,
        db_name="animals_database_1",
        coll_name="horses",
        key="horse-breed",
        value="unicorn",
    )
    assert has_correct_data, "data not written to shard-one"

    # log into shard 2 verify data
    shard_two_client = await generate_mongodb_client(
        ops_test, app_name=SHARD_TWO_APP_NAME, mongos=False
    )
    has_correct_data = verify_data_mongodb(
        shard_two_client,
        db_name="animals_database_2",
        coll_name="horses",
        key="horse-breed",
        value="pegasus",
    )
    assert has_correct_data, "data not written to shard-two"
