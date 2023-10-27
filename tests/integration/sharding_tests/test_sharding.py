#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import pytest
from pytest_operator.plugin import OpsTest

from .helpers import (
    generate_mongodb_client,
    has_correct_shards,
    shard_has_databases,
    verify_data_mongodb,
    write_data_to_mongodb,
)

SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
SHARD_THREE_APP_NAME = "shard-three"
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
        num_units=1,
        config={"role": "config-server"},
        application_name=CONFIG_SERVER_APP_NAME,
    )
    await ops_test.model.deploy(
        my_charm, num_units=1, config={"role": "shard"}, application_name=SHARD_ONE_APP_NAME
    )
    await ops_test.model.deploy(
        my_charm, num_units=1, config={"role": "shard"}, application_name=SHARD_TWO_APP_NAME
    )
    await ops_test.model.deploy(
        my_charm, num_units=1, config={"role": "shard"}, application_name=SHARD_THREE_APP_NAME
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_THREE_APP_NAME],
            idle_period=20,
            raise_on_blocked=False,
            timeout=TIMEOUT,
            raise_on_error=False,
        )

    # TODO Future PR: assert that CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME
    # are blocked waiting for relaitons


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
    await ops_test.model.integrate(
        f"{SHARD_THREE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    async with ops_test.fast_forward():
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

    # TODO Future PR: assert that CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME
    # have the correct active statuses.


@pytest.mark.abort_on_fail
async def test_sharding(ops_test: OpsTest) -> None:
    """Tests writing data to mongos gets propagated to shards."""
    # write data to mongos on both shards.
    mongos_client = await generate_mongodb_client(
        ops_test, app_name=CONFIG_SERVER_APP_NAME, mongos=True
    )

    # write data to shard two
    write_data_to_mongodb(
        mongos_client,
        db_name="animals_database_1",
        coll_name="horses",
        content={"horse-breed": "unicorn", "real": True},
    )
    mongos_client.admin.command("movePrimary", "animals_database_1", to=SHARD_TWO_APP_NAME)

    # write data to shard three
    write_data_to_mongodb(
        mongos_client,
        db_name="animals_database_2",
        coll_name="horses",
        content={"horse-breed": "pegasus", "real": True},
    )
    mongos_client.admin.command("movePrimary", "animals_database_2", to=SHARD_THREE_APP_NAME)

    # log into shard two verify data
    shard_two_client = await generate_mongodb_client(
        ops_test, app_name=SHARD_TWO_APP_NAME, mongos=False
    )
    has_correct_data = verify_data_mongodb(
        shard_two_client,
        db_name="animals_database_1",
        coll_name="horses",
        key="horse-breed",
        value="unicorn",
    )
    assert has_correct_data, "data not written to shard-two"

    # log into shard 2 verify data
    shard_three_client = await generate_mongodb_client(
        ops_test, app_name=SHARD_THREE_APP_NAME, mongos=False
    )
    has_correct_data = verify_data_mongodb(
        shard_three_client,
        db_name="animals_database_2",
        coll_name="horses",
        key="horse-breed",
        value="pegasus",
    )
    assert has_correct_data, "data not written to shard-three"


async def test_shard_removal(ops_test: OpsTest) -> None:
    """Test shard removal.

    This test also verifies that:
    - Databases that are using this shard as a primary are moved.
    - The balancer is turned back on if turned off.
    - Config server supp    orts removing multiple shards.
    """
    # turn off balancer.
    mongos_client = await generate_mongodb_client(
        ops_test, app_name=CONFIG_SERVER_APP_NAME, mongos=True
    )
    mongos_client.admin.command("balancerStop")
    balancer_state = mongos_client.admin.command("balancerStatus")
    assert balancer_state["mode"] == "off", "balancer was not successfully turned off"

    # remove two shards at the same time
    await ops_test.model.applications[CONFIG_SERVER_APP_NAME].remove_relation(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )
    await ops_test.model.applications[CONFIG_SERVER_APP_NAME].remove_relation(
        f"{SHARD_THREE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    async with ops_test.fast_forward():
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

    # TODO future PR: assert statuses are correct

    # verify that config server turned back on the balancer
    balancer_state = mongos_client.admin.command("balancerStatus")
    assert balancer_state["mode"] != "off", "balancer not turned back on from config server"

    # verify sharded cluster config
    assert has_correct_shards(
        mongos_client, expected_shards=[SHARD_ONE_APP_NAME]
    ), "Config server did not process config properly"

    # verify no data lost
    assert shard_has_databases(
        mongos_client,
        shard_name=SHARD_ONE_APP_NAME,
        expected_databases_on_shard=["animals_database_1", "animals_database_2"],
    ), "Not all databases on final shard"


async def test_removal_of_non_primary_shard(ops_test: OpsTest):
    """Tests safe removal of a shard that is not primary."""
    # add back a shard so we can safely remove a shard.
    await ops_test.model.integrate(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    async with ops_test.fast_forward():
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

    await ops_test.model.applications[CONFIG_SERVER_APP_NAME].remove_relation(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
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
        mongos_client, expected_shards=[SHARD_ONE_APP_NAME]
    ), "Config server did not process config properly"

    # verify no data lost
    assert shard_has_databases(
        mongos_client,
        shard_name=SHARD_ONE_APP_NAME,
        expected_databases_on_shard=["animals_database_1", "animals_database_2"],
    ), "Not all databases on final shard"


async def test_unconventual_shard_removal(ops_test: OpsTest):
    """Tests that removing a shard application safely drains data.

    It is preferred that users remove-relations instead of removing shard applications. But we do
    support removing shard applications in a safe way.
    """
    # add back a shard so we can safely remove a shard.
    await ops_test.model.integrate(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    await ops_test.model.remove_application(SHARD_TWO_APP_NAME, block_until_done=True)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME],
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
        mongos_client, expected_shards=[SHARD_ONE_APP_NAME]
    ), "Config server did not process config properly"

    # verify no data lost
    assert shard_has_databases(
        mongos_client,
        shard_name=SHARD_ONE_APP_NAME,
        expected_databases_on_shard=["animals_database_1", "animals_database_2"],
    ), "Not all databases on final shard"
