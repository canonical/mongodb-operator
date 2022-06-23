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


async def run_command_on_unit(unit, command: str) -> Optional[str]:
    """Run a command in one Juju unit.

    Args:
        unit: the Juju unit instance.
        command: the command to run.

    Returns:
        command execution output or none if
        the command produces no output.
    """
    action = await unit.run(command)
    return action.results.get("Stdout", None)


def replica_set_client(replica_ips: List[str], password: str) -> MongoClient:
    """Generates the replica set URI for multiple IP addresses.

    Args:
        replica_ips: list of ips hosting the replica set.
        password: password of database.
    """
    hosts = ["{}:{}".format(replica_ip, PORT) for replica_ip in replica_ips]
    hosts = ",".join(hosts)

    replica_set_uri = f"mongodb://operator:" f"{password}@" f"{hosts}/admin?replicaSet=mongodb"
    return MongoClient(replica_set_uri)


async def fetch_replica_set_members(replica_ips: List[str], ops_test: OpsTest):
    """Fetches the IPs listed as replica set members in the MongoDB replica set configuration.

    Args:
        replica_ips: list of ips hosting the replica set.
        ops_test: reference to deployment.
    """
    # connect to replica set uri
    password = await get_password(ops_test)
    client = replica_set_client(replica_ips, password)

    # get ips from MongoDB replica set configuration
    rs_config = client.admin.command("replSetGetConfig")
    member_ips = []
    for member in rs_config["config"]["members"]:
        # get member ip without ":PORT"
        member_ips.append(member["host"].split(":")[0])

    client.close()

    return member_ips


def unit_uri(ip_address: str, password) -> str:
    """Generates URI that is used by MongoDB to connect to a single replica.

    Args:
        ip_address: ip address of replica/unit
        password: password of database.
    """
    return f"mongodb://operator:" f"{password}@" f"{ip_address}:{PORT}/admin?replicaSet=mongodb"


async def get_password(ops_test: OpsTest) -> str:
    """Use the charm action to retrieve the password from provided unit.

    Returns:
        String with the password stored on the peer relation databag.
    """
    # can retrieve from any unit running unit so we pick the first
    unit_name = ops_test.model.applications[APP_NAME].units[0].name
    unit_id = unit_name.split("/")[1]

    action = await ops_test.model.units.get(f"{APP_NAME}/{unit_id}").run_action(
        "get-admin-password"
    )
    action = await action.wait()
    return action.results["admin-password"]


async def fetch_primary(replica_set_hosts: List[str], ops_test: OpsTest) -> str:
    """Returns IP address of current replica set primary."""
    # connect to MongoDB client
    password = await get_password(ops_test)
    client = replica_set_client(replica_set_hosts, password)

    # grab the replica set status
    try:
        status = client.admin.command("replSetGetStatus")
    except (ConnectionFailure, ConfigurationError, OperationFailure):
        return None
    finally:
        client.close()

    primary = None
    # loop through all members in the replica set
    for member in status["members"]:
        # check replica's current state
        if member["stateStr"] == "PRIMARY":
            # get member ip without ":PORT"
            primary = member["name"].split(":")[0]

    return primary


@retry(
    retry=retry_if_result(lambda x: x is None),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
async def replica_set_primary(replica_set_hosts: List[str], ops_test: OpsTest) -> str:
    """Returns the primary of the replica set.

    Retrying 5 times to give the replica set time to elect a new primary, also checks against the
    valid_ips to verify that the primary is not outdated.

    client:
        client of the replica set of interest.
    valid_ips:
        list of ips that are currently in the replica set.
    """
    primary = await fetch_primary(replica_set_hosts, ops_test)
    # return None if primary is no longer in the replica set
    if primary is not None and primary not in replica_set_hosts:
        return None

    return str(primary)


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


async def find_unit(ops_test: OpsTest, leader: bool) -> ops.model.Unit:
    """Helper function identifies the a unit, based on need for leader or non-leader."""
    ret_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status() == leader:
            ret_unit = unit

    return ret_unit
