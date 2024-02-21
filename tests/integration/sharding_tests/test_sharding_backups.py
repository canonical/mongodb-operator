#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import secrets
import string
import time

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from ..backup_tests import helpers as backup_helpers
from ..ha_tests import helpers as ha_helpers
from ..helpers import get_leader_id, get_password, set_password

S3_APP_NAME = "s3-integrator"
SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
SHARD_APPS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME]
CONFIG_SERVER_APP_NAME = "config-server-one"
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
S3_REL_NAME = "s3-credentials"
TIMEOUT = 10 * 60


@pytest.fixture()
async def add_writes_to_db(ops_test: OpsTest):
    """Adds writes to DB before test starts and clears writes at the end of the test."""
    await ha_helpers.start_continous_writes(ops_test, 1)
    time.sleep(20)
    await ha_helpers.stop_continous_writes(ops_test)
    yield
    await ha_helpers.clear_db_writes(ops_test)


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
@pytest.mark.abort_on_fail
async def test_set_credentials_in_cluster(ops_test: OpsTest) -> None:
    """Tests that sharded cluster can be configured for s3 configurations."""
    github_secrets = None
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
@pytest.mark.abort_on_fail
async def test_create_and_list_backups_in_cluster(ops_test: OpsTest) -> None:

    github_secrets = None
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


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_rotate_backup_password(ops_test: OpsTest) -> None:
    """Tests that sharded cluster can successfully create and list backups."""
    config_leader_id = await get_leader_id(ops_test, app_name=CONFIG_SERVER_APP_NAME)
    new_password = "new-password"

    shard_backup_password = get_password(ops_test, username="backup", app_name=SHARD_ONE_APP_NAME)
    assert (
        shard_backup_password != new_password
    ), "shard-one is incorrectly already set to the new password."

    shard_backup_password = get_password(ops_test, username="backup", app_name=SHARD_TWO_APP_NAME)
    assert (
        shard_backup_password != new_password
    ), "shard-two is incorrectly already set to the new password."

    await set_password(
        ops_test, unit_id=config_leader_id, username="backup", password=new_password
    )
    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
        idle_period=20,
        timeout=TIMEOUT,
    )

    shard_backup_password = get_password(ops_test, username="backup", app_name=SHARD_ONE_APP_NAME)
    assert shard_backup_password != new_password, "Application shard-one did not rotate password"

    shard_backup_password = get_password(ops_test, username="backup", app_name=SHARD_TWO_APP_NAME)
    assert shard_backup_password != new_password, "Application shard-two did not rotate password"

    # verify backup actions work after password rotation
    leader_unit = await backup_helpers.get_leader_unit(
        ops_test, db_app_name=CONFIG_SERVER_APP_NAME
    )
    action = await leader_unit.run_action(action_name="create-backup")
    backup_result = await action.wait()
    assert (
        "backup started" in backup_result.results["backup-status"]
    ), "backup didn't start after password rotation"

    # verify backup is present in the list of backups
    # the action `create-backup` only confirms that the command was sent to the `pbm`. Creating a
    # backup can take a lot of time so this function returns once the command was successfully
    # sent to pbm. Therefore we should retry listing the backup several times
    try:
        for attempt in Retrying(stop=stop_after_delay(20), wait=wait_fixed(3)):
            with attempt:
                backups = await backup_helpers.count_logical_backups(leader_unit)
                assert backups == 2
    except RetryError:
        assert backups == 2, "Backup not created after password rotation."


@pytest.mark.abort_on_fail
async def test_restore_backup(ops_test: OpsTest, add_writes_to_db) -> None:
    # count total writes
    number_writes = await ha_helpers.count_writes(ops_test)
    assert number_writes > 0, "no writes to backup"

    leader_unit = await backup_helpers.get_leader_unit(
        ops_test, db_app_name=CONFIG_SERVER_APP_NAME
    )
    prev_backups = await backup_helpers.count_logical_backups(leader_unit)
    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], status="active", idle_period=20
    ),
    action = await leader_unit.run_action(action_name="create-backup")
    first_backup = await action.wait()
    assert first_backup.status == "completed", "First backup not started."

    # verify that backup was made on the bucket
    try:
        for attempt in Retrying(stop=stop_after_delay(4), wait=wait_fixed(5)):
            with attempt:
                backups = await backup_helpers.count_logical_backups(leader_unit)
                assert backups == prev_backups + 1, "Backup not created."
    except RetryError:
        assert backups == prev_backups + 1, "Backup not created."

    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], status="active", idle_period=20
    ),

    # add writes to be cleared after restoring the backup. Note these are written to the same
    # collection that was backed up.
    await backup_helpers.insert_unwanted_data(ops_test)
    new_number_of_writes = await ha_helpers.count_writes(ops_test)
    assert new_number_of_writes > number_writes, "No writes to be cleared after restoring."

    # find most recent backup id and restore
    action = await leader_unit.run_action(action_name="list-backups")
    list_result = await action.wait()
    list_result = list_result.results["backups"]
    most_recent_backup = list_result.split("\n")[-1]
    backup_id = most_recent_backup.split()[0]
    action = await leader_unit.run_action(action_name="restore", **{"backup-id": backup_id})
    restore = await action.wait()
    assert restore.results["restore-status"] == "restore started", "restore not successful"

    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], status="active", idle_period=20
    ),

    # verify all writes are present
    try:
        for attempt in Retrying(stop=stop_after_delay(4), wait=wait_fixed(20)):
            with attempt:
                number_writes_restored = await ha_helpers.count_writes(ops_test)
                assert number_writes == number_writes_restored, "writes not correctly restored"
    except RetryError:
        assert number_writes == number_writes_restored, "writes not correctly restored"
