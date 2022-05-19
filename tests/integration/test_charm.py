#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os

import pytest
from helpers import (
    APP_NAME,
    PORT,
    UNIT_IDS,
    count_primaries,
    fetch_replica_set_members,
    find_unit,
    replica_set_primary,
    unit_uri,
    get_password
)
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from pytest_operator.plugin import OpsTest
from tenacity import RetryError

logger = logging.getLogger(__name__)


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
    leader_unit = await find_unit(ops_test, leader=True)

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"

    # connect to mongod
    password = await get_password(ops_test)
    client = MongoClient(unit_uri(leader_unit.public_address, password), directConnection=True)

    # verify primary status
    assert client.is_primary, "Leader is not primary"
    client.close()


async def test_exactly_one_primary(ops_test: OpsTest) -> None:
    """Tests that there is exactly one primary in the deployed units."""
    try:
        password = await get_password(ops_test)
        number_of_primaries = count_primaries(ops_test, password)
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
        password = await get_password(ops_test)
        client = MongoClient(unit_uri(unit.public_address, password), directConnection=True)

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


async def test_add_units(ops_test: OpsTest) -> None:
    """Tests juju add-unit functionality.

    Verifies that when a new unit is added to the MongoDB application that it is added to the
    MongoDB replica set configuration.
    """
    # add units and wait for idle
    await ops_test.model.applications[APP_NAME].add_unit(count=2)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)
    assert len(ops_test.model.applications[APP_NAME].units) == 5

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[APP_NAME].units]

    # connect to replica set uri and get replica set members
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test)

    # verify that the replica set members have the correct units
    assert set(member_ips) == set(ip_addresses)


async def test_scale_down_capablities(ops_test: OpsTest) -> None:
    """Tests clusters behavior when scaling down a majority and removing a primary replica.

    This test verifies that the behavior of:
    1.  when a leader is deleted that the new leader, on calling leader_elected will reconfigure
    the replicaset.
    2. primary stepping down leads to a replica set with a new primary.
    3. removing a minority of units (2 out of 5) is feasiable.
    4. race conditions due to removing multiple units is handled.
    5. deleting a non-leader unit is properly handled.
    """
    deleted_unit_ips = []

    # find leader unit
    leader_unit = await find_unit(ops_test, leader=True)

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"
    deleted_unit_ips.append(leader_unit.public_address)

    # find non-leader unit
    non_leader_unit = await find_unit(ops_test, leader=False)
    deleted_unit_ips.append(non_leader_unit.public_address)

    # destroy 2 units simulatenously
    await ops_test.model.destroy_units(
        leader_unit.name,
        non_leader_unit.name,
    )

    # wait for app to be active after removal of unit
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)

    # verify that is three units are running after deletion of two units
    assert len(ops_test.model.applications[APP_NAME].units) == 3

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[APP_NAME].units]

    # check that the replica set with the remaining units has a primary
    try:
        primary = await replica_set_primary(ip_addresses, ops_test)
    except RetryError:
        primary = None

    # verify that the primary is not None
    assert primary is not None, "replica set has no primary"

    # check that the primary is one of the remaining units
    assert primary in ip_addresses, "replica set primary is not one of the available units"

    # verify that the configuration of mongodb no longer has the deleted ip
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test)

    assert set(member_ips) == set(ip_addresses), "mongod config contains deleted units"
