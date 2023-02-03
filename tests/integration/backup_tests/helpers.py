# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import os

import ops
from pytest_operator.plugin import OpsTest

S3_APP_NAME = "s3-integrator"


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


async def count_backups(db_unit: ops.model.Unit) -> int:
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
