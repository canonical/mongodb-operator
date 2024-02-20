#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import secrets
import string

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from ..backup_tests import helpers as backup_helpers

S3_APP_NAME = "s3-integrator"
SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
SHARD_APPS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME]
CONFIG_SERVER_APP_NAME = "config-server-one"
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
S3_REL_NAME = "s3-credentials"
TIMEOUT = 10 * 60


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
        my_charm, num_units=1, config={"role": "shard"}, application_name=SHARD_TWO_APP_NAME
    )

    # deploy the s3 integrator charm
    await ops_test.model.deploy(S3_APP_NAME, channel="edge")

    await ops_test.model.wait_for_idle(
        apps=[S3_APP_NAME, CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
        idle_period=20,
        raise_on_blocked=False,
        timeout=TIMEOUT,
        raise_on_error=False,
    )


@pytest.mark.group(1)
async def test_set_credentials_in_cluster(ops_test: OpsTest, github_secrets) -> None:
    """Tests that sharded cluster can be configured for s3 configurations."""
    await backup_helpers.set_credentials(ops_test, github_secrets, cloud="AWS")
    choices = string.ascii_letters + string.digits
    unique_path = "".join([secrets.choice(choices) for _ in range(4)])
    configuration_parameters = {
        "bucket": "data-charms-testing",
        "path": f"mongodb-vm/test-{unique_path}",
        "endpoint": "https://s3.amazonaws.com",
        "region": "us-east-1",
    }

    # apply new configuration options
    await ops_test.model.applications[S3_APP_NAME].set_config(configuration_parameters)
    await ops_test.model.wait_for_idle(apps=[S3_APP_NAME], status="active", timeout=TIMEOUT)

    # provide config-server to entire cluster and s3-integrator to config-server - integrations
    # made in succession to test race conditions.
    await ops_test.model.integrate(
        f"{S3_APP_NAME}:{S3_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{S3_REL_NAME}",
    )
    await ops_test.model.integrate(
        f"{SHARD_ONE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )
    await ops_test.model.integrate(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )

    await ops_test.model.wait_for_idle(
        apps=[
            CONFIG_SERVER_APP_NAME,
            SHARD_ONE_APP_NAME,
            SHARD_TWO_APP_NAME,
        ],
        idle_period=20,
        status="active",
        timeout=TIMEOUT,
    )


@pytest.mark.group(1)
async def test_create_and_list_backups_in_cluster(ops_test: OpsTest, github_secrets) -> None:
    """Tests that sharded cluster can successfully create and list backups."""
    leader_unit = await backup_helpers.get_leader_unit(
        ops_test, db_app_name=CONFIG_SERVER_APP_NAME
    )
    await backup_helpers.set_credentials(ops_test, github_secrets, cloud="AWS")
    # verify backup list works
    action = await leader_unit.run_action(action_name="list-backups")
    list_result = await action.wait()
    backups = list_result.results["backups"]
    assert backups, "backups not outputted"

    # verify backup is started
    action = await leader_unit.run_action(action_name="create-backup")
    backup_result = await action.wait()
    assert "backup started" in backup_result.results["backup-status"], "backup didn't start"

    # verify backup is present in the list of backups
    # the action `create-backup` only confirms that the command was sent to the `pbm`. Creating a
    # backup can take a lot of time so this function returns once the command was successfully
    # sent to pbm. Therefore we should retry listing the backup several times
    try:
        for attempt in Retrying(stop=stop_after_delay(20), wait=wait_fixed(3)):
            with attempt:
                backups = await backup_helpers.count_logical_backups(leader_unit)
                assert backups == 1
    except RetryError:
        assert backups == 1, "Backup not created."