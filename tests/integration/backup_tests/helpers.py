# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import subprocess

import ops
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_attempt, wait_fixed

from ..ha_tests import helpers as ha_helpers
from ..helpers import get_app_name

S3_APP_NAME = "s3-integrator"
TIMEOUT = 10 * 60


async def destroy_cluster(ops_test: OpsTest, cluster_name: str) -> None:
    """Destroy the cluster and wait for its removal."""
    units = ops_test.model.applications[cluster_name].units
    # best practice to scale down before removing the entire cluster. Wait for cluster to settle
    # removing the next
    for i in range(0, len(units[:-1])):
        unit_name = units[i].name
        await ops_test.model.applications[cluster_name].destroy_unit(unit_name)
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[cluster_name].units) == len(units) - i - 1,
            timeout=TIMEOUT,
        )
        await ops_test.model.wait_for_idle(apps=[cluster_name], status="active")

    # now that the cluster only has one unit left we can remove the application from Juju, send
    # force for a quicker removal of the cluster.
    model_name = ops_test.model.info.name
    subprocess.check_output(
        f"juju remove-application --model={model_name} --force new-mongodb".split()
    )

    # verify there are no more units.
    await ops_test.model.block_until(
        lambda: cluster_name not in ops_test.model.applications,
        timeout=TIMEOUT,
    )


async def create_and_verify_backup(ops_test: OpsTest) -> None:
    """Creates and verifies that a backup was successfully created."""
    db_unit = await get_leader_unit(ops_test)
    prev_backups = await count_logical_backups(db_unit)
    action = await db_unit.run_action(action_name="create-backup")
    backup = await action.wait()
    assert backup.status == "completed", "Backup not started."

    # verify that backup was made on the bucket
    try:
        for attempt in Retrying(stop=stop_after_attempt(4), wait=wait_fixed(5)):
            with attempt:
                backups = await count_logical_backups(db_unit)
                assert backups == prev_backups + 1, "Backup not created."
    except RetryError:
        assert backups == prev_backups + 1, "Backup not created."


async def get_leader_unit(ops_test: OpsTest, db_app_name=None) -> ops.model.Unit:
    """Returns the leader unit of the database charm."""
    db_app_name = db_app_name or await get_app_name(ops_test)
    for unit in ops_test.model.applications[db_app_name].units:
        if await unit.is_leader_from_status():
            return unit


async def get_backup_list(ops_test: OpsTest, db_app_name=None) -> str:
    """Count the number of logical backups."""
    leader_unit = await get_leader_unit(ops_test, db_app_name=db_app_name)
    action = await leader_unit.run_action(action_name="list-backups")
    list_result = await action.wait()
    list_result = list_result.results["backups"]
    return list_result


async def count_logical_backups(db_unit: ops.model.Unit) -> int:
    """Count the number of logical backups."""
    action = await db_unit.run_action(action_name="list-backups")
    list_result = await action.wait()
    list_result = list_result.results["backups"]
    list_result = list_result.split("\n")
    backups = 0
    for res in list_result:
        backups += 1 if "logical" in res else 0

    return backups


async def count_failed_backups(db_unit: ops.model.Unit) -> int:
    """Count the number of failed backups."""
    action = await db_unit.run_action(action_name="list-backups")
    list_result = await action.wait()
    list_result = list_result.results["backups"]
    list_result = list_result.split("\n")
    failed_backups = 0
    for res in list_result:
        failed_backups += 1 if "failed" in res else 0

    return failed_backups


async def set_credentials(ops_test: OpsTest, github_secrets, cloud: str) -> None:
    """Sets the s3 crednetials for the provided cloud, valid options are AWS or GCP."""
    # set access key and secret keys
    access_key = github_secrets[f"{cloud}_ACCESS_KEY"]
    secret_key = github_secrets[f"{cloud}_SECRET_KEY"]
    assert access_key and secret_key, f"{cloud} access key and secret key not provided."

    s3_integrator_unit = ops_test.model.applications[S3_APP_NAME].units[0]
    parameters = {"access-key": access_key, "secret-key": secret_key}
    action = await s3_integrator_unit.run_action(action_name="sync-s3-credentials", **parameters)
    await action.wait()


async def insert_unwanted_data(ops_test: OpsTest) -> None:
    """Inserts the data into the MongoDB cluster via primary replica."""
    app_name = await get_app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    primary = (await ha_helpers.replica_set_primary(ip_addresses, ops_test)).public_address
    password = await ha_helpers.get_password(ops_test, app_name)
    client = MongoClient(ha_helpers.unit_uri(primary, password, app_name), directConnection=True)
    db = client["new-db"]
    test_collection = db["test_collection"]
    test_collection.insert_one({"unwanted_data": "bad data 1"})
    test_collection.insert_one({"unwanted_data": "bad data 2"})
    test_collection.insert_one({"unwanted_data": "bad data 3"})
    client.close()
