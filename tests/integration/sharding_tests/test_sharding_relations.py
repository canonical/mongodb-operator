#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import pytest
from juju.errors import JujuAPIError
from pytest_operator.plugin import OpsTest

SHARD_ONE_APP_NAME = "shard-one"
CONFIG_SERVER_ONE_APP_NAME = "config-server-one"
CONFIG_SERVER_TWO_APP_NAME = "config-server-two"
APP_CHARM_NAME = "application"

CONFIG_SERVER_REL_NAME = "config-server"
SHARD_REL_NAME = "sharding"
DATABASE_REL_NAME = "first-database"

# for now we have a large timeout due to the slow drainage of the `config.system.sessions`
# collection. More info here:
# https://stackoverflow.com/questions/77364840/mongodb-slow-chunk-migration-for-collection-config-system-sessions-with-remov
TIMEOUT = 30 * 60


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, application_charm, database_charm) -> None:
    """Build and deploy a sharded cluster."""
    await ops_test.model.deploy(
        database_charm,
        config={"role": "config-server"},
        application_name=CONFIG_SERVER_ONE_APP_NAME,
    )
    await ops_test.model.deploy(
        database_charm,
        config={"role": "config-server"},
        application_name=CONFIG_SERVER_TWO_APP_NAME,
    )
    await ops_test.model.deploy(
        database_charm, num_units=1, config={"role": "shard"}, application_name=SHARD_ONE_APP_NAME
    )
    await ops_test.model.deploy(application_charm, application_name=APP_CHARM_NAME)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[
                CONFIG_SERVER_ONE_APP_NAME,
                CONFIG_SERVER_TWO_APP_NAME,
                SHARD_ONE_APP_NAME,
            ],
            idle_period=20,
            raise_on_blocked=False,
            timeout=TIMEOUT,
        )


async def test_only_one_config_server_relation(ops_test: OpsTest) -> None:
    """Verify that a shard can only be related to one config server."""
    await ops_test.model.integrate(
        f"{SHARD_ONE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_ONE_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    multiple_config_server_rels_allowed = True
    try:
        await ops_test.model.integrate(
            f"{SHARD_ONE_APP_NAME}:{SHARD_REL_NAME}",
            f"{CONFIG_SERVER_TWO_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
        )
    except JujuAPIError as e:
        if e.error_code == "quota limit exceeded":
            multiple_config_server_rels_allowed = False

    assert not multiple_config_server_rels_allowed, "Shard can relate to multiple config servers."


async def test_cannot_use_db_relation(ops_test: OpsTest) -> None:
    """Verify that a shard cannot use the DB relation."""
    await ops_test.model.integrate(
        f"{APP_CHARM_NAME}:{DATABASE_REL_NAME}",
        SHARD_ONE_APP_NAME,
    )

    shard_unit = ops_test.model.applications[SHARD_ONE_APP_NAME].units[0]
    assert (
        shard_unit.workload_status_message == "Sharding roles do not support database interface."
    ), "Shard cannot be related using the database relation"
