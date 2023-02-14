# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import os

import ops
from tests.integration.ha_tests.helpers import MongoClient, get_password, subprocess
from pytest_operator.plugin import OpsTest

S3_APP_NAME = "s3-integrator"


async def clear_db_writes(ops_test: OpsTest) -> bool:
    """Stop the DB process and remove any writes to the test collection."""
    await stop_continous_writes(ops_test)

    # remove collection from database
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    client = MongoClient(connection_string)
    db = client["admin"]

    # collection for continuous writes
    test_collection = db["test_collection"]
    test_collection.drop()

    # collection for replication tests
    test_collection = db["test_ubuntu_collection"]
    test_collection.drop()

    client.close()


async def start_continous_writes(ops_test: OpsTest, starting_number: int) -> None:
    """Starts continuous writes to MongoDB with available replicas.

    In the future this should be put in a dummy charm.
    """
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    # run continuous writes in the background.
    subprocess.Popen(
        [
            "python3",
            "tests/integration/backup_tests/continuous_writes.py",
            connection_string,
            str(starting_number),
        ]
    )


async def stop_continous_writes(ops_test: OpsTest, down_unit=None) -> int:
    """Stops continuous writes to MongoDB and returns the last written value.

    In the future this should be put in a dummy charm.
    """
    # stop the process
    proc = subprocess.Popen(["pkill", "-9", "-f", "continuous_writes.py"])

    # wait for process to be killed
    proc.communicate()

    app = await app_name(ops_test)
    password = await get_password(ops_test, app, down_unit)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]

    # last written value should be the highest number in the database.
    last_written_value = test_collection.find_one(sort=[("number", -1)])
    client.close()
    return last_written_value


async def count_writes(ops_test: OpsTest, down_unit=None) -> int:
    """New versions of pymongo no longer support the count operation, instead find is used."""
    app = await app_name(ops_test)
    password = await get_password(ops_test, app, down_unit)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    client = MongoClient(connection_string)
    db = client["admin"]
    test_collection = db["test_collection"]
    count = test_collection.count_documents({})
    client.close()
    return count


async def app_name(ops_test: OpsTest) -> str:
    """Returns the name of the cluster running MongoDB.

    This is important since not all deployments of the MongoDB charm have the application name
    "mongodb".

    Note: if multiple clusters are running MongoDB this will return the one first found.
    """
    status = await ops_test.model.get_status()
    for app in ops_test.model.applications:
        # note that format of the charm field is not exactly "mongodb" but instead takes the form
        # of `local:focal/mongodb-6`
        if "mongodb" in status["applications"][app]["charm"]:
            return app

    return None


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


async def set_credentials(ops_test: OpsTest, cloud: str) -> None:
    """Sets the s3 crednetials for the provided cloud, valid options are AWS or GCP."""
    # set access key and secret keys
    access_key = os.environ.get(f"{cloud}_ACCESS_KEY", False)
    secret_key = os.environ.get(f"{cloud}_SECRET_KEY", False)
    assert access_key and secret_key, f"{cloud} access key and secret key not provided."

    s3_integrator_unit = ops_test.model.applications[S3_APP_NAME].units[0]
    parameters = {"access-key": access_key, "secret-key": secret_key}
    action = await s3_integrator_unit.run_action(action_name="sync-s3-credentials", **parameters)
    await action.wait()


def is_relation_joined(ops_test: OpsTest, endpoint_one: str, endpoint_two: str) -> bool:
    """Check if a relation is joined.

    Args:
        ops_test: The ops test object passed into every test case
        endpoint_one: The first endpoint of the relation
        endpoint_two: The second endpoint of the relation
    """
    for rel in ops_test.model.relations:
        endpoints = [endpoint.name for endpoint in rel.endpoints]
        if endpoint_one in endpoints and endpoint_two in endpoints:
            return True
    return False
