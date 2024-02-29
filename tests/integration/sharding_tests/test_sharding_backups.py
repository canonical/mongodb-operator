#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import secrets
import string
import time

import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, stop_after_delay, wait_fixed

from ..backup_tests import helpers as backup_helpers

# from .writes_helpers import writes_helpers
from ..helpers import get_leader_id, get_password, set_password
from . import writes_helpers

S3_APP_NAME = "s3-integrator"
SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
CONFIG_SERVER_APP_NAME = "config-server"
SHARD_APPS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME]
CLUSTER_APPS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME, CONFIG_SERVER_APP_NAME]
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
S3_REL_NAME = "s3-credentials"
OPERATOR_PASSWORD = "operator-password"
TIMEOUT = 10 * 60


@pytest.fixture()
async def add_writes_to_db(ops_test: OpsTest):
    """Adds writes to DB before test starts and clears writes at the end of the test."""
    await writes_helpers.start_continous_writes(
        ops_test, 1, config_server_name=CONFIG_SERVER_APP_NAME
    )
    time.sleep(20)
    await writes_helpers.stop_continous_writes(ops_test, config_server_name=CONFIG_SERVER_APP_NAME)
    yield
    await writes_helpers.clear_db_writes(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy a sharded cluster."""
    await deploy_cluster_backup_test(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
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
    await setup_cluster_and_s3(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_create_and_list_backups_in_cluster(ops_test: OpsTest) -> None:
    """Tests that sharded cluster can successfully create and list backups."""
    # verify backup list works
    backups = await backup_helpers.get_backup_list(ops_test, db_app_name=CONFIG_SERVER_APP_NAME)
    assert backups, "backups not outputted"

    # verify backup is started
    leader_unit = await backup_helpers.get_leader_unit(
        ops_test, db_app_name=CONFIG_SERVER_APP_NAME
    )
    action = await leader_unit.run_action(action_name="create-backup")
    backup_result = await action.wait()
    assert "backup started" in backup_result.results["backup-status"], "backup didn't start"

    # verify backup is present in the list of backups
    # the action `create-backup` only confirms that the command was sent to the `pbm`. Creating a
    # backup can take a lot of time so this function returns once the command was successfully
    # sent to pbm. Therefore we should retry listing the backup several times
    for attempt in Retrying(stop=stop_after_delay(TIMEOUT), wait=wait_fixed(3), reraise=True):
        with attempt:
            backups = await backup_helpers.count_logical_backups(leader_unit)
            assert backups == 1


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_shards_cannot_run_backup_actions(ops_test: OpsTest) -> None:
    shard_unit = await backup_helpers.get_leader_unit(ops_test, db_app_name=SHARD_ONE_APP_NAME)
    action = await shard_unit.run_action(action_name="create-backup")
    attempted_backup = await action.wait()
    assert attempted_backup.status == "failed", "shard ran create-backup command."

    action = await shard_unit.run_action(action_name="list-backups")
    attempted_backup = await action.wait()
    assert attempted_backup.status == "failed", "shard ran list-backup command."

    action = await shard_unit.run_action(action_name="restore")
    attempted_backup = await action.wait()
    assert attempted_backup.status == "failed", "shard ran list-backup command."


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_rotate_backup_password(ops_test: OpsTest) -> None:
    """Tests that sharded cluster can successfully create and list backups."""
    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
        idle_period=20,
        timeout=TIMEOUT,
        status="active",
    )
    config_leader_id = await get_leader_id(ops_test, app_name=CONFIG_SERVER_APP_NAME)
    new_password = "new-password"

    shard_backup_password = await get_password(
        ops_test, username="backup", app_name=SHARD_ONE_APP_NAME
    )
    assert (
        shard_backup_password != new_password
    ), "shard-one is incorrectly already set to the new password."

    shard_backup_password = await get_password(
        ops_test, username="backup", app_name=SHARD_TWO_APP_NAME
    )
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
        status="active",
    )
    config_svr_backup_password = await get_password(
        ops_test, username="backup", app_name=CONFIG_SERVER_APP_NAME
    )

    assert (
        config_svr_backup_password == new_password
    ), "Application config-srver did not rotate password"

    shard_backup_password = await get_password(
        ops_test, username="backup", app_name=SHARD_ONE_APP_NAME
    )
    assert shard_backup_password == new_password, "Application shard-one did not rotate password"

    shard_backup_password = await get_password(
        ops_test, username="backup", app_name=SHARD_TWO_APP_NAME
    )
    assert shard_backup_password == new_password, "Application shard-two did not rotate password"

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
    for attempt in Retrying(stop=stop_after_delay(20), wait=wait_fixed(3), reraise=True):
        with attempt:
            backups = await backup_helpers.count_logical_backups(leader_unit)
            assert backups == 2, "Backup not created after password rotation."


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_restore_backup(ops_test: OpsTest, add_writes_to_db) -> None:
    """Tests that sharded Charmed MongoDB cluster supports restores."""
    # count total writes
    cluster_writes = await writes_helpers.get_cluster_writes_count(
        ops_test, shard_app_names=SHARD_APPS
    )
    assert cluster_writes["total_writes"] > 0, "no writes to backup"

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
    for attempt in Retrying(stop=stop_after_delay(4), wait=wait_fixed(5), reraise=True):
        with attempt:
            backups = await backup_helpers.count_logical_backups(leader_unit)
            assert backups == prev_backups + 1, "Backup not created."

    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], status="active", idle_period=20
    ),

    # add writes to be cleared after restoring the backup. Note these are written to the same
    # collection that was backed up.
    await writes_helpers.insert_unwanted_data(ops_test)
    new_total_writes = await writes_helpers.get_cluster_writes_count(
        ops_test, shard_app_names=SHARD_APPS
    )
    assert (
        new_total_writes["total_writes"] > cluster_writes["total_writes"]
    ), "No writes to be cleared after restoring."

    # find most recent backup id and restore
    list_result = await backup_helpers.get_backup_list(
        ops_test, db_app_name=CONFIG_SERVER_APP_NAME
    )
    most_recent_backup = list_result.split("\n")[-1]
    backup_id = most_recent_backup.split()[0]
    action = await leader_unit.run_action(action_name="restore", **{"backup-id": backup_id})
    restore = await action.wait()
    assert restore.results["restore-status"] == "restore started", "restore not successful"

    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], status="active", idle_period=20
    ),

    # verify all writes are present
    for attempt in Retrying(stop=stop_after_delay(4), wait=wait_fixed(20), reraise=True):
        with attempt:
            restored_total_writes = await writes_helpers.get_cluster_writes_count(
                ops_test, shard_app_names=SHARD_APPS
            )
            assert (
                restored_total_writes["total_writes"] == cluster_writes["total_writes"]
            ), "writes not correctly restored to whole cluster"
            assert (
                restored_total_writes[SHARD_ONE_APP_NAME] == cluster_writes[SHARD_ONE_APP_NAME]
            ), f"writes not correctly restored to {SHARD_ONE_APP_NAME}"
            assert (
                restored_total_writes[SHARD_TWO_APP_NAME] == cluster_writes[SHARD_TWO_APP_NAME]
            ), f"writes not correctly restored to {SHARD_TWO_APP_NAME}"


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_migrate_restore_backup(ops_test: OpsTest, add_writes_to_db) -> None:
    """Tests that sharded Charmed MongoDB cluster supports restores."""
    config_leader_id = await get_leader_id(ops_test, app_name=CONFIG_SERVER_APP_NAME)
    await set_password(
        ops_test, unit_id=config_leader_id, username="operator", password=OPERATOR_PASSWORD
    )
    await ops_test.model.wait_for_idle(apps=CLUSTER_APPS, status="active", idle_period=20),

    # count total writes
    cluster_writes = await writes_helpers.get_cluster_writes_count(
        ops_test, shard_app_names=SHARD_APPS
    )
    assert cluster_writes["total_writes"] > 0, "no writes to backup"

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
    for attempt in Retrying(stop=stop_after_delay(4), wait=wait_fixed(5), reraise=True):
        with attempt:
            backups = await backup_helpers.count_logical_backups(leader_unit)
            assert backups == prev_backups + 1, "Backup not created."

    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], status="active", idle_period=20
    ),

    # add writes to be cleared after restoring the backup. Note these are written to the same
    # collection that was backed up.
    await writes_helpers.insert_unwanted_data(ops_test)
    new_total_writes = await writes_helpers.get_cluster_writes_count(
        ops_test, shard_app_names=SHARD_APPS
    )
    assert (
        new_total_writes["total_writes"] > cluster_writes["total_writes"]
    ), "No writes to be cleared after restoring."

    # Destroy the old cluster and create a new cluster with the same exact topology and password
    await destroy_cluster_backup_test(ops_test)
    await deploy_cluster_backup_test(ops_test, deploy_s3_integrator=False)
    await setup_cluster_and_s3(ops_test)
    config_leader_id = await get_leader_id(ops_test, app_name=CONFIG_SERVER_APP_NAME)
    await set_password(
        ops_test, unit_id=config_leader_id, username="operator", password=OPERATOR_PASSWORD
    )
    await ops_test.model.wait_for_idle(
        apps=CLUSTER_APPS, status="active", idle_period=20, timeout=TIMEOUT
    ),

    # find most recent backup id and restore
    leader_unit = await backup_helpers.get_leader_unit(
        ops_test, db_app_name=CONFIG_SERVER_APP_NAME
    )

    # find most recent backup id and restore
    list_result = await backup_helpers.get_backup_list(
        ops_test, db_app_name=CONFIG_SERVER_APP_NAME
    )
    most_recent_backup = list_result.split("\n")[-1]
    backup_id = most_recent_backup.split()[0]
    action = await leader_unit.run_action(action_name="restore", **{"backup-id": backup_id})
    restore = await action.wait()
    assert restore.results["restore-status"] == "restore started", "restore not successful"

    await ops_test.model.wait_for_idle(
        apps=[CONFIG_SERVER_APP_NAME], status="active", idle_period=20
    ),

    # verify all writes are present
    for attempt in Retrying(stop=stop_after_delay(4), wait=wait_fixed(20), reraise=True):
        with attempt:
            restored_total_writes = await writes_helpers.get_cluster_writes_count(
                ops_test, shard_app_names=SHARD_APPS
            )
            assert (
                restored_total_writes["total_writes"] == cluster_writes["total_writes"]
            ), "writes not correctly restored to whole cluster"
            assert (
                restored_total_writes[SHARD_ONE_APP_NAME] == cluster_writes[SHARD_ONE_APP_NAME]
            ), f"writes not correctly restored to {SHARD_ONE_APP_NAME}"
            assert (
                restored_total_writes[SHARD_TWO_APP_NAME] == cluster_writes[SHARD_TWO_APP_NAME]
            ), f"writes not correctly restored to {SHARD_TWO_APP_NAME}"


async def deploy_cluster_backup_test(ops_test: OpsTest, deploy_s3_integrator=True) -> None:
    """Deploy a cluster for the backup test."""
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
    if deploy_s3_integrator:
        await ops_test.model.deploy(S3_APP_NAME, channel="edge")

    await ops_test.model.wait_for_idle(
        apps=[S3_APP_NAME, CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
        idle_period=20,
        raise_on_blocked=False,
        timeout=TIMEOUT,
        raise_on_error=False,
    )


async def setup_cluster_and_s3(ops_test: OpsTest) -> None:
    """Deploy a cluster for the backup test."""
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


async def destroy_cluster_backup_test(ops_test):
    """Destroy cluster in a forceful way."""
    for app in [
        CONFIG_SERVER_APP_NAME,
        SHARD_ONE_APP_NAME,
        SHARD_TWO_APP_NAME,
    ]:
        await ops_test.model.applications[app].destroy(force=True, no_wait=False)

    # destroy does not wait for applications to be removed, perform this check manually
    for attempt in Retrying(stop=stop_after_attempt(100), wait=wait_fixed(10), reraise=True):
        with attempt:
            # pytest_operator has a bug where the number of applications does not get correctly
            # updated. Wrapping the call with `fast_forward` resolves this
            async with ops_test.fast_forward():
                print(ops_test.model.applications)
                assert (
                    len(ops_test.model.applications) == 1
                ), "old cluster not destroyed successfully."
