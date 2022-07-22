# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from typing import List, Optional

import ops
import yaml
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, ConnectionFailure, OperationFailure
from pytest_operator.plugin import OpsTest
from tenacity import retry, retry_if_result, stop_after_attempt, wait_exponential

_PERMISSION_MASK_FOR_SCP = 644
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
