#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import pytest
from pytest_operator.plugin import OpsTest

from ..helpers import get_password

SHARD_ONE_APP_NAME = "shard-one"
CONFIG_SERVER_APP_NAME = "config-server-one"
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
MONGODB_KEYFILE_PATH = "/var/snap/charmed-mongodb/current/etc/mongod/keyFile"

"""
Integration tests are not a requirement for our release goal of POC Sharding. However they are
useful for automating tests that developers must do by hand. This file currently exists to help
running tests during the development of sharding.

TODO Future tests:
- shard can only relate to one config server
- shard cannot change passwords
"""


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy a sharded cluster."""
    async with ops_test.fast_forward():
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
        await ops_test.model.wait_for_idle(
            apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME], status="active"
        )

    await ops_test.model.integrate(
        f"{SHARD_ONE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )
    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME], status="active"
    )


async def test_shared_operator_password(ops_test: OpsTest) -> None:
    """Verify sharded components have the same passwords."""
    shard_password = await get_password(ops_test, SHARD_ONE_APP_NAME)
    config_password = await get_password(ops_test, CONFIG_SERVER_APP_NAME)
    assert (
        shard_password == config_password
    ), "sharding components do not have the same operator password."


async def test_shared_keyfile(ops_test: OpsTest) -> None:
    """Verify sharded components have the same keyfile contents."""
    config_unit = ops_test.model.applications[CONFIG_SERVER_APP_NAME].units[0]
    config_key_file = await get_keyfile_contents(config_unit)

    shard_unit = ops_test.model.applications[SHARD_ONE_APP_NAME].units[0]
    shard_key_file = await get_keyfile_contents(shard_unit)

    assert config_key_file == shard_key_file, "shards and config server using different keyfiles"


async def get_keyfile_contents(ops_test: OpsTest, unit) -> str:
    cat_cmd = f"exec --unit {unit.name} -- cat {MONGODB_KEYFILE_PATH}"
    return_code, output, _ = await ops_test.juju(*cat_cmd.split())

    if return_code != 0:
        raise ProcessError(
            f"Expected cat command {cat_cmd} to succeed instead it failed: {return_code}"
        )


class ProcessError(Exception):
    """Raised when a process fails."""
