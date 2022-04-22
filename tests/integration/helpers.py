# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import tempfile
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


async def pull_content_from_unit_file(unit, path: str) -> str:
    """Pull the content of a file from one unit.

    Args:
        unit: the Juju unit instance.
        path: the path of the file to get the contents from.

    Returns:
        the entire content of the file.
    """
    # Get the file's original access permission mask.
    result = await run_command_on_unit(unit, f"stat -c %a {path}")
    permissions = result.strip()
    permissions_changed = False
    # Change the permission in order to be able to retrieve the file using the ubuntu user.
    if permissions != _PERMISSION_MASK_FOR_SCP:
        await run_command_on_unit(unit, f"chmod {_PERMISSION_MASK_FOR_SCP} {path}")
        permissions_changed = True

    # Get the contents of the file.
    temp_file = tempfile.NamedTemporaryFile()
    await unit.scp_from(path, temp_file.name, scp_opts=["-v"])
    data = temp_file.read().decode("utf-8")
    temp_file.close()

    # Change the file permissions back to the original mask.
    if permissions_changed:
        await run_command_on_unit(unit, f"chmod {permissions} {path}")

    return data


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


def replica_set_client(replica_ips: List[str]) -> MongoClient:
    """Generates the replica set URI for multiple IP addresses.

    Args:
        replica_ips: list of ips hosting the replica set.
    """
    if len(replica_ips) == 1:
        replica_set_uri = replica_ips[0] + ":" + str(PORT)
        return MongoClient(replica_set_uri, replicaset="rs0")
    else:
        replica_set_uri = "mongodb://"
        hosts = ["{}:{}".format(replica_ip, PORT) for replica_ip in replica_ips]
        replica_set_uri += ",".join(hosts)
        replica_set_uri += "/replicaSet=rs0"
        return MongoClient(replica_set_uri)


def fetch_replica_set_members(replica_ips: List[str]):
    """Fetches the IPs listed as replica set members in the MongoDB replica set configuration.

    Args:
        replica_ips: list of ips hosting the replica set.
    """
    # connect to replica set uri
    client = replica_set_client(replica_ips)

    # get ips from MongoDB replica set configuration
    rs_config = client.admin.command("replSetGetConfig")
    member_ips = []
    for member in rs_config["config"]["members"]:
        # get member ip without ":PORT"
        member_ips.append(member["host"].split(":")[0])

    client.close()

    return member_ips


def update_bind_ip(conf: str, ip_address: str) -> str:
    """Updates mongod.conf contents to use the given ip address for bindIp.

    Args:
        conf: contents of mongod.conf
        ip_address: ip address of unit
    """
    mongo_config = yaml.safe_load(conf)
    mongo_config["net"]["bindIp"] = "localhost,{}".format(ip_address)
    return yaml.dump(mongo_config)


def unit_uri(ip_address: str) -> str:
    """Generates URI that is used by MongoDB to connect to a single replica.

    Args:
        ip_address: ip address of replica/unit
    """
    return "mongodb://{}:{}/".format(ip_address, PORT)


def fetch_primary(replica_set_hosts: List[str]) -> str:
    """Returns IP address of current replica set primary."""
    # connect to MongoDB client
    client = replica_set_client(replica_set_hosts)

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
def replica_set_primary(replica_set_hosts: List[str]) -> str:
    """Returns the primary of the replica set.

    Retrying 5 times to give the replica set time to elect a new primary, also checks against the
    valid_ips to verify that the primary is not outdated.

    client:
        client of the replica set of interest.
    valid_ips:
        list of ips that are currently in the replica set.
    """
    primary = fetch_primary(replica_set_hosts)
    # return None if primary is no longer in the replica set
    if primary is not None and primary not in replica_set_hosts:
        return None

    return str(primary)


@retry(
    retry=retry_if_result(lambda x: x == 0),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
def count_primaries(ops_test: OpsTest) -> int:
    """Counts the number of primaries in a replica set.

    Will retry counting when the number of primaries is 0 at most 5 times.
    """
    number_of_primaries = 0
    for unit_id in UNIT_IDS:
        # get unit
        unit = ops_test.model.applications[APP_NAME].units[unit_id]

        # connect to mongod
        client = MongoClient(unit_uri(unit.public_address))

        # check primary status
        if client.is_primary:
            number_of_primaries += 1

    return number_of_primaries


async def find_leader_unit(ops_test: OpsTest) -> ops.model.Unit:
    """Helper function identifies the leader unit.

    Returns:
        leader unit
    """
    leader_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit

    return leader_unit
