#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
import os
import pytest
import yaml
from typing import Tuple, List
from pytest_operator.plugin import OpsTest
from helpers import pull_content_from_unit_file
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from tenacity import (
    RetryError, retry, retry_if_result, stop_after_attempt, wait_exponential
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
    expected_mongodb_conf = update_bind_ip(
        expected_mongodb_conf, unit.public_address)
    assert expected_mongodb_conf == unit_mongodb_conf_data


@pytest.mark.parametrize("unit_id", UNIT_IDS)
async def test_unit_is_running_as_replica_set(
    ops_test: OpsTest, unit_id: int
) -> None:
    """Tests that mongodb is running as a replica set for the application unit.
    """
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


async def test_all_units_in_same_replica_set(ops_test: OpsTest) -> None:
    """Tests that all units in the application belong to the same replica set.

    This test will be implemented by Raul as part of his onboarding task.

    Hint: multiple ways to do this, here are two but there are probably
    other ways to implement it:
    - check that each unit has the same replica set name
    - create a URI for all units for the expected replica set name and see if
      you can connect
    """
    pass


async def test_leader_is_primary_on_deployment(ops_test: OpsTest) -> None:
    """Tests that right after deployment that the primary unit is the leader.
    """
    # grab leader unit
    leader_unit = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_unit = unit

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"

    # connect to mongod
    client = MongoClient(unit_uri(leader_unit.public_address))

    # verify primary status
    assert client.is_primary, "Leader is not primary"
    client.close()


async def test_exactly_one_primary(ops_test: OpsTest) -> None:
    """Tests that there is exactly one primary in the deployed units.
    """
    try:
        number_of_primaries = count_primaries(ops_test)
    except RetryError:
        number_of_primaries = 0

    # check that exactly of the units is the leader
    assert number_of_primaries == 1, "Expected one unit to be a primary: %s != 1" % (
        number_of_primaries
    )


async def test_cluster_is_stable_after_deletion(ops_test: OpsTest) -> None:
    """Tests that the cluster maintains a primary after the primary is delelted.
    """
    # find & destroy leader unit
    leader_ip = None
    for unit in ops_test.model.applications[APP_NAME].units:
        if await unit.is_leader_from_status():
            leader_ip = unit.public_address
            await unit.destroy()
            break

    # wait for app to be active after removal of unit
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)

    # verify that ther are two units running after deletion of leader
    assert len(ops_test.model.applications[APP_NAME].units) == 2

    # grab remaining IPS, must compare against leader_ip since it is not
    # gaurenteed that the leader unit will be fully shutdown
    ip_addresses = []
    for unit in ops_test.model.applications[APP_NAME].units:
        if not unit.public_address == leader_ip:
            ip_addresses.append(unit.public_address)

    # check that the replica set with the remaining units has a primary
    replica_set_uri = "mongodb://{}:27017,{}:27017/replicaSet=rs0".format(
        ip_addresses[0], ip_addresses[1]
    )
    client = MongoClient(replica_set_uri)
    try:
        primary = replica_set_primary(client, valid_ips=ip_addresses)
    except RetryError:
        primary = None

    print(client.primary)
    client.close()

    # verify that the primary is not None
    assert primary is not None, "replica set with uri %s has no primary" % (
        replica_set_uri)

    # check that the primary is not one of the deleted units
    print(primary[0])
    assert primary[0] in ip_addresses, (
        "replica set primary is not one of the available units")


def update_bind_ip(conf: str, ip_address: str) -> str:
    """Updates mongod.conf contents to use the given ip address for bindIp.

    Args:
        conf: contents of mongod.conf
        ip_address: ip adress of unit
    """
    mongo_config = yaml.safe_load(conf)
    mongo_config["net"]["bindIp"] = "localhost,{}".format(ip_address)
    return yaml.dump(mongo_config)


def unit_uri(ip_address: str) -> str:
    """Generates URI that is used by MongoDB to connect to a single replica.

    Args:
        ip_address: ip address of replica/unit
    """
    return "mongodb://{}:27017/".format(ip_address)


def is_none(value):
    """Return True if value is None."""
    return value is None


@retry(
    retry=retry_if_result(is_none),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
def replica_set_primary(
    client: MongoClient, valid_ips: List[str]
) -> Tuple[str, str]:
    """Returns the primary of the replica set, retrying 5 times to give the
    replica set time to elect a new primary, also checks against the valid_ips
    to verify that the primary is not outdated.

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


def is_zero(value):
    """Return True if value is 0."""
    return value == 0


@retry(
    retry=retry_if_result(is_zero),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
def count_primaries(ops_test: OpsTest) -> int:
    """Counts the number of primaries in a replica set. Will retry counting
    when the number of primaries is 0 at most 5 times.
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
