# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from typing import List

import ops
import yaml
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest
from tenacity import retry, retry_if_result, stop_after_attempt, wait_exponential

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PORT = 27017
APP_NAME = METADATA["name"]
UNIT_IDS = [0, 1, 2]


def unit_uri(ip_address: str, password, app=APP_NAME) -> str:
    """Generates URI that is used by MongoDB to connect to a single replica.

    Args:
        ip_address: ip address of replica/unit
        password: password of database.
        app: name of application which has the cluster.
    """
    return f"mongodb://operator:" f"{password}@" f"{ip_address}:{PORT}/admin?replicaSet={app}"


async def get_password(ops_test: OpsTest, app=APP_NAME) -> str:
    """Use the charm action to retrieve the password from provided unit.

    Returns:
        String with the password stored on the peer relation databag.
    """
    # can retrieve from any unit running unit so we pick the first
    unit_name = ops_test.model.applications[app].units[0].name
    unit_id = unit_name.split("/")[1]

    action = await ops_test.model.units.get(f"{app}/{unit_id}").run_action("get-admin-password")
    action = await action.wait()
    return action.results["admin-password"]


@retry(
    retry=retry_if_result(lambda x: x == 0),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
def count_primaries(ops_test: OpsTest, password: str) -> int:
    """Counts the number of primaries in a replica set.

    Will retry counting when the number of primaries is 0 at most 5 times.
    """
    number_of_primaries = 0
    for unit_id in UNIT_IDS:
        # get unit
        unit = ops_test.model.applications[APP_NAME].units[unit_id]

        # connect to mongod
        client = MongoClient(unit_uri(unit.public_address, password), directConnection=True)

        # check primary status
        if client.is_primary:
            number_of_primaries += 1

    return number_of_primaries


async def find_unit(ops_test: OpsTest, leader: bool, app=APP_NAME) -> ops.model.Unit:
    """Helper function identifies the a unit, based on need for leader or non-leader."""
    ret_unit = None
    for unit in ops_test.model.applications[app].units:
        if await unit.is_leader_from_status() == leader:
            ret_unit = unit

    return ret_unit


async def unit_ids(ops_test: OpsTest) -> List[int]:
    """Provides a function for generating unit_ids in case a cluster is provided."""
    provided_cluster = await ha_on_provided_cluster(ops_test)
    if not provided_cluster:
        return UNIT_IDS
    unit_ids = [
        unit.name.split("/")[1] for unit in ops_test.model.applications[provided_cluster].units
    ]
    return unit_ids


async def ha_on_provided_cluster(ops_test: OpsTest) -> str:
    """Returns the name of a cluster provided for HA testing.
    This is important since not all deployments of the MongoDB charm have the application name
    MongoDB.
    """
    status = await ops_test.model.get_status()
    for app in ops_test.model.applications:
        # note that format of the charm field is not exactly "mongodb" but instead takes the form
        # of `local:focal/mongodb-6`
        if "mongodb" in status["applications"][app]["charm"]:
            return app
    return None


async def app_name(ops_test: OpsTest) -> str:
    """Returns the name of the app being used for testing."""
    status = await ops_test.model.get_status()
    for app in ops_test.model.applications:
        # note that format of the charm field is not exactly "mongodb" but instead takes the form
        # of `local:focal/mongodb-6`
        if "mongodb" in status["applications"][app]["charm"]:
            return app

    return APP_NAME
