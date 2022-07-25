# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from typing import List

import ops
import yaml
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, ConnectionFailure, OperationFailure
from pytest_operator.plugin import OpsTest
from tenacity import retry, retry_if_result, stop_after_attempt, wait_exponential

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PORT = 27017
APP_NAME = METADATA["name"]
UNIT_IDS = [0, 1, 2]


def replica_set_client(replica_ips: List[str], password: str, app=APP_NAME) -> MongoClient:
    """Generates the replica set URI for multiple IP addresses.

    Args:
        replica_ips: list of ips hosting the replica set.
        password: password of database.
        app: name of application which hosts the cluster.
    """
    hosts = ["{}:{}".format(replica_ip, PORT) for replica_ip in replica_ips]
    hosts = ",".join(hosts)

    replica_set_uri = f"mongodb://operator:" f"{password}@" f"{hosts}/admin?replicaSet={app}"
    return MongoClient(replica_set_uri)


async def fetch_replica_set_members(replica_ips: List[str], ops_test: OpsTest, app=APP_NAME):
    """Fetches the IPs listed as replica set members in the MongoDB replica set configuration.

    Args:
        replica_ips: list of ips hosting the replica set.
        ops_test: reference to deployment.
        app: name of application which has the cluster.
    """
    # connect to replica set uri
    password = await get_password(ops_test, app)
    client = replica_set_client(replica_ips, password, app)

    # get ips from MongoDB replica set configuration
    rs_config = client.admin.command("replSetGetConfig")
    member_ips = []
    for member in rs_config["config"]["members"]:
        # get member ip without ":PORT"
        member_ips.append(member["host"].split(":")[0])

    client.close()

    return member_ips


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


async def fetch_primary(replica_set_hosts: List[str], ops_test: OpsTest, app=APP_NAME) -> str:
    """Returns IP address of current replica set primary."""
    # connect to MongoDB client
    password = await get_password(ops_test, app)
    client = replica_set_client(replica_set_hosts, password, app)

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
async def replica_set_primary(
    replica_set_hosts: List[str], ops_test: OpsTest, app=APP_NAME
) -> str:
    """Returns the primary of the replica set.

    Retrying 5 times to give the replica set time to elect a new primary, also checks against the
    valid_ips to verify that the primary is not outdated.

    client:
        client of the replica set of interest.
    valid_ips:
        list of ips that are currently in the replica set.
    """
    primary = await fetch_primary(replica_set_hosts, ops_test, app)
    # return None if primary is no longer in the replica set
    if primary is not None and primary not in replica_set_hosts:
        return None

    return str(primary)


async def find_unit(ops_test: OpsTest, leader: bool, app=APP_NAME) -> ops.model.Unit:
    """Helper function identifies the a unit, based on need for leader or non-leader."""
    ret_unit = None
    for unit in ops_test.model.applications[app].units:
        if await unit.is_leader_from_status() == leader:
            ret_unit = unit

    return ret_unit


async def retrieve_entries(ops_test, app, db_name, collection_name, query_field):
    """Retries entries from a specified collection within a specified database."""
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    password = await get_password(ops_test, app)
    client = replica_set_client(ip_addresses, password, app)

    db = client[db_name]
    test_collection = db[collection_name]

    # read all entries from original cluster
    cursor = test_collection.find({})
    cluster_entries = set()
    for document in cursor:
        cluster_entries.add(document[query_field])

    client.close()
    return cluster_entries


async def insert_entry(client, db_name, collection_name, entry):
    """Inserts a new entry into the cluster database."""
    db = client[db_name]
    test_collection = db[collection_name]
    test_collection.insert(entry)
