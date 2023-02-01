#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import os
import helpers
import pytest
import asyncio
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    Retrying,
    stop_after_delay,
    wait_fixed,
)

S3_APP_NAME = "s3-integrator"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for HA testing. Hence check if there
    # is a pre-existing cluster.
    if await helpers.app_name(ops_test):
        return

    db_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(db_charm, num_units=1)

    # TODO remove this once s3-integrator charm is published.
    # build and deploy the s3 integrator
    charm_path = "tests/integration/backup_tests/s3-integrator"
    s3_charm = await ops_test.build_charm(charm_path)
    await ops_test.model.deploy(s3_charm, num_units=1)
    await ops_test.model.wait_for_idle()


@pytest.mark.abort_on_fail
async def test_install_pbm(ops_test: OpsTest) -> None:
    """Verifies that pbm snap was installed."""
    app = await helpers.app_name(ops_test)
    unit = ops_test.model.applications[app].units[0]
    pbm_cmd = f"run --unit {unit.name} percona-backup-mongodb"
    return_code, _, _ = await ops_test.juju(*pbm_cmd.split())
    assert return_code == 0, "percona-backup-mongodb not installed"


@pytest.mark.abort_on_fail
async def test_blocked_incorrect_s3(ops_test: OpsTest) -> None:
    """Verifies that the charm goes into blocked status when s3 credentials are not compatible."""
    db_app_name = await helpers.app_name(ops_test)

    # set access key and secret keys
    access_key = os.environ.get("AWS_ACCESS_KEY_1", False)
    secret_key = os.environ.get("SECRET_ACCESS_KEY_1", False)
    assert access_key and secret_key, "Access key and secret key not provided."

    s3_integrator_unit = ops_test.model.applications[S3_APP_NAME].units[0]
    parameters = {"access-key": access_key, "secret-key": secret_key}
    action = await s3_integrator_unit.run_action(action_name="sync-s3-credentials", **parameters)
    await action.wait()

    # relate after s3 becomes active
    async with ops_test.fast_forward():
        ops_test.model.wait_for_idle(apps=[S3_APP_NAME], status="active", raise_on_blocked=True)
    await ops_test.model.add_relation(S3_APP_NAME, db_app_name)

    # wait correct application statuses
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[S3_APP_NAME], status="active"),
            ops_test.model.wait_for_idle(apps=[db_app_name], status="blocked"),
        )

    db_unit = ops_test.model.applications[db_app_name].units[0]
    print(db_unit.agent_status_message)
    print(db_unit.agent_status)
    print(db_unit.workload_status)
    print(db_unit.workload_status_message)

    configuration_parameters = {
        "bucket": "pbm-test-bucket-1",
        "path": "data/pbm/backup",
        "region": "us-west-2",
    }

    # apply new configuration options
    await ops_test.model.applications[S3_APP_NAME].set_config(configuration_parameters)

    # after applying correct config options the applications should both be active
    async with ops_test.fast_forward():
        await asyncio.gather(
            ops_test.model.wait_for_idle(apps=[S3_APP_NAME], status="active"),
            ops_test.model.wait_for_idle(apps=[db_app_name], status="active"),
        )


@pytest.mark.abort_on_fail
async def test_create_and_list_backups(ops_test: OpsTest) -> None:
    db_app_name = await helpers.app_name(ops_test)
    db_unit = ops_test.model.applications[db_app_name].units[0]

    # verify backup list works
    action = await db_unit.run_action(action_name="list-backups")
    list_result = await action.wait()
    backups = list_result.results["backups"]
    assert "Backup snapshots" in backups, "backups not listed"
    backups = backups.split("\n")
    original_number_of_backups = len(backups)

    # verify backup is started
    action = await db_unit.run_action(action_name="create-backup")
    backup_result = await action.wait()
    assert backup_result.results["backup-status"] == "backup started", "backup didn't start"

    # verify backup is present in the list of backups
    # the action `create-backup` only confirms that the command was sent to the `pbm`. Creating a
    # backup can take a lot of time so this function returns once the command was successfully
    # sent to pbm. Therefore we should retry listing the backup several times
    try:
        for attempt in Retrying(stop=stop_after_delay(20), wait=wait_fixed(3)):
            with attempt:
                action = await db_unit.run_action(action_name="list-backups")
                list_result = await action.wait()
                backups = list_result.results["backups"]
                backups = backups.split("\n")
                assert len(backups) > original_number_of_backups
    except RetryError:
        assert False, "Backup not created."


@pytest.mark.abort_on_fail
async def test_multi_backup(ops_test: OpsTest, add_writes_to_db) -> None:

    db_app_name = await helpers.app_name(ops_test)
    db_unit = ops_test.model.applications[db_app_name].units[0]

    action = await db_unit.run_action(action_name="create-backup")
    await action.wait()

    # change access key and secret keys
    access_key = os.environ.get("AWS_ACCESS_KEY_2", False)
    secret_key = os.environ.get("SECRET_ACCESS_KEY_2", False)
    assert access_key and secret_key, "Second access key and secret key not provided."
    s3_integrator_unit = ops_test.model.applications[S3_APP_NAME].units[0]
    parameters = {"access-key": access_key, "secret-key": secret_key}
    action = await s3_integrator_unit.run_action(action_name="sync-s3-credentials", **parameters)
    await action.wait()

    # change bucket name
    configuration_parameters = {
        "bucket": "pbm-test-bucket-3",
    }
    await ops_test.model.applications[S3_APP_NAME].set_config(configuration_parameters)

    # create a backup as soon as possible. might not be immediately possible since only one backup
    # can happen at a time.
    try:
        for attempt in Retrying(stop=stop_after_delay(40), wait=wait_fixed(5)):
            with attempt:
                action = await db_unit.run_action(action_name="create-backup")
                second_backup = await action.wait()
                assert second_backup.status == "success"
    except RetryError:
        assert False, "Second backup not created."

    # verify that backups were bade in both: `pbm-bucket-1` and `pbm-bucket-3`
