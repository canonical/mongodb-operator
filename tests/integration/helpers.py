# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from pathlib import Path
from typing import Dict, Optional

import ops
import yaml
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest
from tenacity import retry, retry_if_result, stop_after_attempt, wait_exponential

from .ha_tests.helpers import app_name

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PORT = 27017
APP_NAME = METADATA["name"]
UNIT_IDS = [0, 1, 2]
SERIES = "jammy"


def unit_uri(ip_address: str, password, app=APP_NAME) -> str:
    """Generates URI that is used by MongoDB to connect to a single replica.

    Args:
        ip_address: ip address of replica/unit
        password: password of database.
        app: name of application which has the cluster.
    """
    return f"mongodb://operator:" f"{password}@" f"{ip_address}:{PORT}/admin?replicaSet={app}"


async def get_password(ops_test: OpsTest, username="operator") -> str:
    """Use the charm action to retrieve the password from provided unit.

    Returns:
        String with the password stored on the peer relation databag.
    """
    app = await app_name(ops_test)

    # can retrieve from any unit running unit so we pick the first
    unit_name = ops_test.model.applications[app].units[0].name
    unit_id = unit_name.split("/")[1]

    action = await ops_test.model.units.get(f"{app}/{unit_id}").run_action(
        "get-password", **{"username": username}
    )
    action = await action.wait()
    return action.results["password"]


@retry(
    retry=retry_if_result(lambda x: x == 0),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
async def count_primaries(ops_test: OpsTest, password: str) -> int:
    """Counts the number of primaries in a replica set.

    Will retry counting when the number of primaries is 0 at most 5 times.
    """
    app = await app_name(ops_test)
    number_of_primaries = 0
    for unit_id in UNIT_IDS:
        # get unit
        unit = ops_test.model.applications[app].units[unit_id]

        # connect to mongod
        client = MongoClient(unit_uri(unit.public_address, password, app), directConnection=True)

        # check primary status
        if client.is_primary:
            number_of_primaries += 1

    return number_of_primaries


async def find_unit(ops_test: OpsTest, leader: bool) -> ops.model.Unit:
    """Helper function identifies the a unit, based on need for leader or non-leader."""
    app = await app_name(ops_test)
    ret_unit = None
    for unit in ops_test.model.applications[app].units:
        if await unit.is_leader_from_status() == leader:
            ret_unit = unit

    return ret_unit


async def get_leader_id(ops_test: OpsTest) -> int:
    """Returns the unit number of the juju leader unit."""
    app = await app_name(ops_test)
    for unit in ops_test.model.applications[app].units:
        if await unit.is_leader_from_status():
            return int(unit.name.split("/")[1])
    return -1


async def set_password(
    ops_test: OpsTest, unit_id: int, username: str = "operator", password: str = "secret"
) -> str:
    """Use the charm action to retrieve the password from provided unit.

    Returns:
    String with the password stored on the peer relation databag.
    """
    app = await app_name(ops_test)
    action = await ops_test.model.units.get(f"{app}/{unit_id}").run_action(
        "set-password", **{"username": username, "password": password}
    )
    action = await action.wait()
    return action.results


async def get_application_relation_data(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
    key: str,
    relation_id: str = None,
    relation_alias: str = None,
) -> Optional[str]:
    """Get relation data for an application.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        relation_name: name of the relation to get connection data from
        key: key of data to be retrieved
        relation_id: id of the relation to get connection data from
        relation_alias: alias of the relation (like a connection name)
            to get connection data from
    Returns:
        the that that was requested or None
            if no data in the relation
    Raises:
        ValueError if it's not possible to get application unit data
            or if there is no data for the particular relation endpoint
            and/or alias.
    """
    unit_name = f"{application_name}/0"
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]

    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)

    # Filter the data based on the relation name.
    relation_data = [v for v in data[unit_name]["relation-info"] if v["endpoint"] == relation_name]

    if relation_id:
        # Filter the data based on the relation id.
        relation_data = [v for v in relation_data if v["relation-id"] == relation_id]

    if relation_alias:
        # Filter the data based on the cluster/relation alias.
        relation_data = [
            v
            for v in relation_data
            if json.loads(v["application-data"]["data"])["alias"] == relation_alias
        ]

    if len(relation_data) == 0:
        raise ValueError(
            f"no relation data could be grabbed on relation with endpoint {relation_name} and alias {relation_alias}"
        )

    return relation_data[0]["application-data"].get(key)


async def get_secret_id(ops_test, app_or_unit: Optional[str] = None) -> str:
    """Retrieve secert ID for an app or unit."""
    complete_command = "list-secrets"

    prefix = ""
    if app_or_unit:
        if app_or_unit[-1].isdigit():
            # it's a unit
            app_or_unit = "-".join(app_or_unit.split("/"))
            prefix = "unit-"
        else:
            prefix = "application-"
        complete_command += f" --owner {prefix}{app_or_unit}"

    _, stdout, _ = await ops_test.juju(*complete_command.split())
    output_lines_split = [line.split() for line in stdout.split("\n")]
    if app_or_unit:
        return [line[0] for line in output_lines_split if app_or_unit in line][0]
    else:
        return output_lines_split[1][0]


async def get_secret_content(ops_test, secret_id) -> Dict[str, str]:
    """Retrieve contents of a Juju Secret."""
    secret_id = secret_id.split("/")[-1]
    complete_command = f"show-secret {secret_id} --reveal --format=json"
    _, stdout, _ = await ops_test.juju(*complete_command.split())
    data = json.loads(stdout)
    return data[secret_id]["content"]["Data"]
