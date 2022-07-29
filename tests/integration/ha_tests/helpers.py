# # Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import subprocess
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


async def fetch_replica_set_members(replica_ips: List[str], ops_test: OpsTest):
    """Fetches the IPs listed as replica set members in the MongoDB replica set configuration.

    Args:
        replica_ips: list of ips hosting the replica set.
        ops_test: reference to deployment.
        app: name of application which has the cluster.
    """
    # connect to replica set uri
    app = await app_name(ops_test)
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


async def get_password(ops_test: OpsTest, app) -> str:
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


async def fetch_primary(replica_set_hosts: List[str], ops_test: OpsTest) -> str:
    """Returns IP address of current replica set primary."""
    # connect to MongoDB client
    app = await app_name(ops_test)
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
async def replica_set_primary(replica_set_hosts: List[str], ops_test: OpsTest) -> str:
    """Returns the primary of the replica set.

    Retrying 5 times to give the replica set time to elect a new primary, also checks against the
    valid_ips to verify that the primary is not outdated.
    """
    primary = await fetch_primary(replica_set_hosts, ops_test)
    # return None if primary is no longer in the replica set
    if primary is not None and primary not in replica_set_hosts:
        return None

    return str(primary)


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


async def find_unit(ops_test: OpsTest, leader: bool) -> ops.model.Unit:
    """Helper function identifies the a unit, based on need for leader or non-leader."""
    ret_unit = None
    app = await app_name(ops_test)
    for unit in ops_test.model.applications[app].units:
        if await unit.is_leader_from_status() == leader:
            ret_unit = unit

    return ret_unit


async def unit_ids(ops_test: OpsTest) -> List[int]:
    """Provides a function for generating unit_ids in case a cluster is provided."""
    provided_cluster = await app_name(ops_test)
    if not provided_cluster:
        return UNIT_IDS
    unit_ids = [
        unit.name.split("/")[1] for unit in ops_test.model.applications[provided_cluster].units
    ]
    return unit_ids


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


def storage_type(ops_test, app):
    """Retrieves type of storage associated with an application.

    Note: this function exists as a temporary solution until this issue is resolved:
    https://github.com/juju/python-libjuju/issues/694
    """
    model_name = ops_test.model.info.name
    proc = subprocess.check_output(f"juju storage --model={model_name}".split())
    proc = proc.decode("utf-8")
    for line in proc.splitlines():
        if "Storage" in line:
            continue

        if len(line) == 0:
            continue

        if "detached" in line:
            continue

        unit_name = line.split()[0]
        app_name = unit_name.split("/")[0]
        if app_name == app:
            return line.split()[3]


def storage_id(ops_test, unit_name):
    """Retrieves  storage id associated with provided unit.

    Note: this function exists as a temporary solution until this issue is resolved:
    https://github.com/juju/python-libjuju/issues/694
    """
    model_name = ops_test.model.info.name
    proc = subprocess.check_output(f"juju storage --model={model_name}".split())
    proc = proc.decode("utf-8")
    for line in proc.splitlines():
        if "Storage" in line:
            continue

        if len(line) == 0:
            continue

        if "detached" in line:
            continue

        if line.split()[0] == unit_name:
            return line.split()[1]


async def add_unit_with_storage(ops_test, app, storage):
    """Adds unit with storage.

    Note: this function exists as a temporary solution until this issue is resolved:
    https://github.com/juju/python-libjuju/issues/695
    """
    expected_units = len(ops_test.model.applications[app].units) + 1
    prev_units = [unit.name for unit in ops_test.model.applications[app].units]
    model_name = ops_test.model.info.name
    add_unit_cmd = f"add-unit {app} --model={model_name} --attach-storage={storage}".split()
    await ops_test.juju(*add_unit_cmd)
    await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=1000)
    assert (
        len(ops_test.model.applications[app].units) == expected_units
    ), "New unit not added to model"

    # verify storage attached
    curr_units = [unit.name for unit in ops_test.model.applications[app].units]
    new_unit = list(set(curr_units) - set(prev_units))[0]
    assert storage_id(ops_test, new_unit) == storage, "unit added with incorrect storage"

    # return a reference to newly added unit
    for unit in ops_test.model.applications[app].units:
        if unit.name == new_unit:
            return unit


async def reused_storage(ops_test: OpsTest, unit_ip) -> bool:
    """Returns True if storage provided to mongod has been reused.

    MongoDB startup message indicates storage reuse:
        If member transitions to STARTUP2 from STARTUP then it is syncing/getting data from
        primary.
        If member transitions to STARTUP2 from REMOVED then it is re-using the storage we
        provided.
    """
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    client = MongoClient(unit_uri(unit_ip, password, app), directConnection=True)
    log = client.admin.command("getLog", "global")
    client.close()

    for item in log["log"]:
        item = json.loads(item)

        if "attr" not in item:
            continue

        if item["attr"] == {"newState": "STARTUP2", "oldState": "REMOVED"}:
            return True

    return False
