#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
from pathlib import Path
from typing import List, Tuple

import ops
import pytest
import yaml
from helpers import pull_content_from_unit_file
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    retry,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
UNIT_IDS = [0, 1, 2]
PORT = 27017


@pytest.mark.skipif(
    os.environ.get("PYTEST_SKIP_DEPLOY", False),
    reason="skipping deploy, model expected to be provided.",
)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=len(UNIT_IDS))
    await ops_test.model.wait_for_idle()


@pytest.mark.abort_on_fail
async def test_status(ops_test: OpsTest) -> None:
    """Verifies that the application and unit are active."""
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)
    assert len(ops_test.model.applications[APP_NAME].units) == len(UNIT_IDS)


@pytest.mark.parametrize("unit_id", UNIT_IDS)
async def test_config_files_are_correct(ops_test: OpsTest, unit_id: int) -> None:
    """Tests that mongo.conf as expected content."""
    # Get the expected contents from files.
    with open("tests/data/mongod.conf") as file:
        expected_mongodb_conf = file.read()

    # Pull the configuration files from MongoDB instance.
    unit = ops_test.model.applications[f"{APP_NAME}"].units[unit_id]

    # Check that the conf settings are as expected.
    unit_mongodb_conf_data = await pull_content_from_unit_file(unit, "/etc/mongod.conf")
    expected_mongodb_conf = update_bind_ip(expected_mongodb_conf, unit.public_address)
    assert expected_mongodb_conf == unit_mongodb_conf_data


@pytest.mark.parametrize("unit_id", UNIT_IDS)
async def test_unit_is_running_as_replica_set(ops_test: OpsTest, unit_id: int) -> None:
    """Tests that mongodb is running as a replica set for the application unit."""
    # connect to mongo replica set
    unit = ops_test.model.applications[APP_NAME].units[unit_id]
    connection = unit.public_address + ":" + str(PORT)
    client = MongoClient(connection, replicaset="rs0")

    # check mongo replica set is ready
    try:
        client.server_info()
    except ServerSelectionTimeoutError:
        assert False, "server is not ready"

    # close connection
    client.close()


async def test_leader_is_primary_on_deployment(ops_test: OpsTest) -> None:
    """Tests that right after deployment that the primary unit is the leader."""
    # grab leader unit
    leader_unit = await find_leader_unit(ops_test)

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"

    # connect to mongod
    client = MongoClient(unit_uri(leader_unit.public_address))

    # verify primary status
    assert client.is_primary, "Leader is not primary"
    client.close()


async def test_exactly_one_primary(ops_test: OpsTest) -> None:
    """Tests that there is exactly one primary in the deployed units."""
    try:
        number_of_primaries = count_primaries(ops_test)
    except RetryError:
        number_of_primaries = 0

    # check that exactly of the units is the leader
    assert number_of_primaries == 1, "Expected one unit to be a primary: {} != 1".format(
        number_of_primaries
    )


async def test_get_primary_action(ops_test: OpsTest) -> None:
    """Tests that action get-primary outputs the correct unit with the primary replica."""
    # determine which unit is the primary
    expected_primary = None
    for unit in ops_test.model.applications[APP_NAME].units:
        # connect to mongod
        client = MongoClient(unit_uri(unit.public_address))

        # check primary status
        if client.is_primary:
            expected_primary = unit.name
            break

    # verify that there is a primary
    assert expected_primary

    # check if get-primary returns the correct primary unit regardless of
    # which unit the action is run on
    for unit in ops_test.model.applications[APP_NAME].units:
        # use get-primary action to find primary
        action = await unit.run_action("get-primary")
        action = await action.wait()
        identified_primary = action.results["replica-set-primary"]

        # assert get-primary returned the right primary
        assert identified_primary == expected_primary


async def test_cluster_is_stable_after_leader_deletion(ops_test: OpsTest) -> None:
    """Tests that the cluster behavior after planned leader unit removal.

    This test verifies that the behavior of when a leader is deleted that the new leader, on
    calling leader_elected will reconfigure the replicaset. Similarly, this tests the case of a
    primary steping down, since on deployment it is maintained that the leader is primary.
    """
    # find & destroy leader unit
    # grab leader unit
    leader_unit = await find_leader_unit(ops_test)

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"

    # save ip and delete leader
    leader_ip = leader_unit.public_address
    await leader_unit.destroy()

    # wait for app to be active after removal of leader
    # issuing dummy update_status to re-trigger event
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)

    # reset update_status
    await ops_test.model.set_config({"update-status-hook-interval": "5m"})

    # verify that there are two units running after deletion of leader
    assert len(ops_test.model.applications[APP_NAME].units) == 2

    # verify that a new leader has been elected
    # grab leader unit
    leader_unit = await find_leader_unit(ops_test)

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"

    # grab IPS
    ip_addresses = []
    for unit in ops_test.model.applications[APP_NAME].units:
        ip_addresses.append(unit.public_address)

    # connect to mongo replica set
    # check that the replica set with the remaining units has a primary
    replica_set_uri = "mongodb://{}:{},{}:{}/replicaSet=rs0".format(
        ip_addresses[0], PORT, ip_addresses[1], PORT
    )
    client = MongoClient(replica_set_uri)

    # grab primary
    try:
        primary = replica_set_primary(client, valid_ips=ip_addresses)
    except RetryError:
        primary = None

    # verify that the primary is not None
    assert primary is not None, "replica set with uri {} has no primary".format(replica_set_uri)

    # check that the primary is one of the remaining units
    assert primary[0] in ip_addresses, "replica set primary is not one of the available units"

    # verify that the configuration of mongodb no longer has the deleted ip
    removed_from_config = True
    rs_config = client.admin.command("replSetGetConfig")
    for member in rs_config["config"]["members"]:
        # get member ip without ":PORT"
        member_ip = member["host"].split(":")[0]
        if member_ip == leader_ip:
            removed_from_config = False

    assert removed_from_config, "removed unit is still present in replica set config"
    client.close()


async def test_cluster_is_stable_after_non_leader_deletion(ops_test: OpsTest) -> None:
    """Tests that the cluster behavior after planned non-leader unit removal.

    This test verifies that the behavior of when a non-leader is deleted that the current leader
    will reconfigure the replicaset.
    """
    # find & destroy non-leader unit
    non_leader_ip = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if not await unit.is_leader_from_status():
            non_leader_ip = unit.public_address
            await unit.destroy()
            break

    # wait for app to be active after removal of unit
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)

    # verify that is one unit running after deletion of non-leader
    assert len(ops_test.model.applications[APP_NAME].units) == 1

    # grab IPS
    ip_addresses = []
    for unit in ops_test.model.applications[APP_NAME].units:
        ip_addresses.append(unit.public_address)

    # check that the replica set with the remaining units has a primary
    # connect to replica set uri
    replica_set_uri = ip_addresses[0] + ":" + str(PORT)
    client = MongoClient(replica_set_uri, replicaset="rs0")

    try:
        primary = replica_set_primary(client, valid_ips=ip_addresses)
    except RetryError:
        primary = None

    # verify that the primary is not None
    assert primary is not None, "replica set with uri {} has no primary".format(replica_set_uri)

    # check that the primary is not one of the deleted units
    assert primary[0] in ip_addresses, "replica set primary is not one of the available units"

    # verify that the configuration of mongodb no longer has the deleted ip
    removed_from_config = True
    rs_config = client.admin.command("replSetGetConfig")
    for member in rs_config["config"]["members"]:
        # get member ip without ":PORT"
        member_ip = member["host"].split(":")[0]
        if member_ip == non_leader_ip:
            removed_from_config = False

    assert removed_from_config, "removed unit is still present in replica set config"
    client.close()


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


@retry(
    retry=retry_if_result(lambda x: x is None),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
def replica_set_primary(client: MongoClient, valid_ips: List[str]) -> Tuple[str, str]:
    """Returns the primary of the replica set.

    Retrying 5 times to give the replica set time to elect a new primary, also checks against the
    valid_ips to verify that the primary is not outdated.

    client:
        client of the replica set of interest.
    valid_ips:
        list of ips that are currently in the replica set.
    """
    primary = client.primary

    # return None if primary is no longer in the replica set
    if primary is not None and primary[0] not in valid_ips:
        primary = None

    return primary


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
