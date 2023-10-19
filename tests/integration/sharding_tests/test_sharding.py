#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import pytest
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest

from .helpers import generate_connection_string

SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
CONFIG_SERVER_APP_NAME = "config-server-one"
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
MONGODB_KEYFILE_PATH = "/var/snap/charmed-mongodb/current/etc/mongod/keyFile"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy a sharded cluster."""
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(
        my_charm,
        num_units=3,
        config={"role": "config-server"},
        application_name=CONFIG_SERVER_APP_NAME,
    )
    await ops_test.model.deploy(
        my_charm, num_units=3, config={"role": "shard"}, application_name=SHARD_ONE_APP_NAME
    )
    await ops_test.model.deploy(
        my_charm, num_units=3, config={"role": "shard"}, application_name=SHARD_TWO_APP_NAME
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
            idle_period=20,
            raise_on_blocked=False,
        )

    # TODO Future PR: assert that CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME
    # are blocked waiting for relaitons


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
        )

    # TODO Future PR: assert that CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME
    # have the correct active statuses.


async def test_sharding(ops_test: OpsTest) -> None:
    """Tests writing data to mongos gets propagated to shards."""
    # write data to mongos router
    mongos_connection_string = await generate_connection_string(
        ops_test, app_name=CONFIG_SERVER_APP_NAME, mongos=True
    )
    client = MongoClient(mongos_connection_string)

    db = client["animals_database_1"]
    horses_collection = db["horses"]
    unicorn = {"horse-breed": "unicorn", "real": True}
    horses_collection.insert_one(unicorn)
    client.admin.command("movePrimary", "animals_database_1", to=SHARD_ONE_APP_NAME)

    db = client["animals_database_2"]
    horses_collection = db["horses"]
    unicorn = {"horse-breed": "pegasus", "real": True}
    horses_collection.insert_one(unicorn)
    client.admin.command("movePrimary", "animals_database_2", to=SHARD_TWO_APP_NAME)

    # log into shard 1 verify its presence
    shard_one_connection_string = await generate_connection_string(
        ops_test, app_name=SHARD_ONE_APP_NAME, mongos=False
    )
    client = MongoClient(shard_one_connection_string)
    db = client["animals_database_1"]
    test_collection = db["horses"]
    query = test_collection.find({}, {"horse-breed": 1})
    assert query[0]["horse-breed"] == "unicorn", "data not written to shard-one"

    # log into shard 2 verify its presence
    shard_two_connection_string = await generate_connection_string(
        ops_test, app_name=SHARD_TWO_APP_NAME, mongos=False
    )
    client = MongoClient(shard_two_connection_string)
    db = client["animals_database_2"]
    test_collection = db["horses"]
    query = test_collection.find({}, {"horse-breed": 1})
    assert query[0]["horse-breed"] == "pegasus", "data not written to shard-two"
