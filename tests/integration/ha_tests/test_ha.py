#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.ha_tests.helpers import (
    APP_NAME,
    app_name,
    fetch_replica_set_members,
    find_unit,
    get_password,
    replica_set_client,
    replica_set_primary,
    retrieve_entries,
    unit_ids,
    unit_uri,
    start_continous_writes,
    update_continuous_writes,
)

logger = logging.getLogger(__name__)

ANOTHER_DATABASE_APP_NAME = "another-database-a"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for HA testing. Hence check if there
    # is a pre-existing cluster.
    if await app_name(ops_test):
        await start_continous_writes(ops_test, 0)
        return

    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=3)
    await ops_test.model.wait_for_idle()
    await start_continous_writes(ops_test, 0)


@pytest.mark.abort_on_fail
async def test_add_units(ops_test: OpsTest) -> None:
    """Tests juju add-unit functionality.

    Verifies that when a new unit is added to the MongoDB application that it is added to the
    MongoDB replica set configuration.
    """
    app = await app_name(ops_test)

    # add units and wait for idle
    expected_units = len(await unit_ids(ops_test)) + 2
    await ops_test.model.applications[app].add_unit(count=2)
    await update_continuous_writes(ops_test)
    await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=1000)
    assert len(ops_test.model.applications[app].units) == expected_units

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]

    # connect to replica set uri and get replica set members
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test)

    # verify that the replica set members have the correct units
    assert set(member_ips) == set(ip_addresses)


@pytest.mark.abort_on_fail
async def test_scale_down_capablities(ops_test: OpsTest) -> None:
    """Tests clusters behavior when scaling down a minority and removing a primary replica.

    - NOTE: on a provided cluster this calculates the largest set of minority members and removes
    them, the primary is guaranteed to be one of those minority members.

    This test verifies that the behavior of:
    1.  when a leader is deleted that the new leader, on calling leader_elected will reconfigure
    the replicaset.
    2. primary stepping down leads to a replica set with a new primary.
    3. removing a minority of units (2 out of 5) is feasiable.
    4. race conditions due to removing multiple units is handled.
    5. deleting a non-leader unit is properly handled.
    """
    deleted_unit_ips = []
    app = await app_name(ops_test)
    units_to_remove = []
    minority_count = int(len(ops_test.model.applications[app].units) / 2)

    # find leader unit
    leader_unit = await find_unit(ops_test, leader=True)
    minority_count -= 1

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"
    deleted_unit_ips.append(leader_unit.public_address)
    units_to_remove.append(leader_unit.name)

    # find non-leader units to remove such that the largest minority possible is removed.
    avail_units = []
    for unit in ops_test.model.applications[app].units:
        if not unit.name == leader_unit.name:
            avail_units.append(unit)

    for _ in range(minority_count):
        unit_to_remove = avail_units.pop()
        deleted_unit_ips.append(unit_to_remove.public_address)
        units_to_remove.append(unit_to_remove.name)

    # destroy units simulatenously
    expected_units = len(await unit_ids(ops_test)) - len(units_to_remove)
    await ops_test.model.destroy_units(*units_to_remove)
    await update_continuous_writes(ops_test)

    # wait for app to be active after removal of units
    await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=1000)

    # verify that is three units are running after deletion of two units
    assert len(ops_test.model.applications[app].units) == expected_units

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]

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


async def test_replication_across_members(ops_test: OpsTest) -> None:
    """Check consistency, ie write to primary, read data from secondaries."""
    # first find primary, write to primary, then read from each unit
    app = await app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    primary = await replica_set_primary(ip_addresses, ops_test)
    password = await get_password(ops_test, app)
    client = MongoClient(unit_uri(primary, password, app), directConnection=True)
    db = client["new-db"]
    test_collection = db["test_collection"]
    test_collection.insert({"release_name": "Focal Fossa", "version": 20.04, "LTS": True})

    client.close()

    secondaries = set(ip_addresses) - set([primary])
    for secondary in secondaries:
        client = MongoClient(unit_uri(secondary, password, app), directConnection=True)

        db = client["new-db"]
        test_collection = db["test_collection"]
        query = test_collection.find({}, {"release_name": 1})
        assert query[0]["release_name"] == "Focal Fossa"

        client.close()


async def test_unique_cluster_dbs(ops_test: OpsTest) -> None:
    """Verify unique clusters do not share DBs."""
    # deploy new cluster
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=1, application_name=ANOTHER_DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle()

    # write data to new cluster
    ip_addresses = [
        unit.public_address
        for unit in ops_test.model.applications[ANOTHER_DATABASE_APP_NAME].units
    ]
    password = await get_password(ops_test, app=ANOTHER_DATABASE_APP_NAME)
    client = replica_set_client(ip_addresses, password, app=ANOTHER_DATABASE_APP_NAME)
    db = client["new-db"]
    test_collection = db["test_collection"]
    test_collection.insert({"release_name": "Jammy Jelly", "version": 22.04, "LTS": False})

    cluster_1_entries = await retrieve_entries(
        ops_test,
        app=ANOTHER_DATABASE_APP_NAME,
        db_name="new-db",
        collection_name="test_collection",
        query_field="release_name",
    )

    cluster_2_entries = await retrieve_entries(
        ops_test,
        app=APP_NAME,
        db_name="new-db",
        collection_name="test_collection",
        query_field="release_name",
    )

    common_entries = cluster_2_entries.intersection(cluster_1_entries)
    assert len(common_entries) == 0, "Writes from one cluster are replicated to another cluster."


async def test_replication_member_scaling(ops_test: OpsTest) -> None:
    """Verify newly added and newly removed members properly replica data.

    Verify newly members have replicated data and newly removed members are gone without data.
    """
    app = await app_name(ops_test)
    original_ip_addresses = [
        unit.public_address for unit in ops_test.model.applications[app].units
    ]
    expected_units = len(await unit_ids(ops_test)) + 1
    await ops_test.model.applications[app].add_unit(count=1)
    await update_continuous_writes(ops_test)
    await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=1000)
    assert len(ops_test.model.applications[app].units) == expected_units

    new_ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    new_member_ip = list(set(new_ip_addresses) - set(original_ip_addresses))[0]
    password = await get_password(ops_test, app)
    client = MongoClient(unit_uri(new_member_ip, password, app), directConnection=True)

    # check for replicated data while retrying to give time for replica to copy over data.
    try:
        for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(3)):
            with attempt:
                db = client["new-db"]
                test_collection = db["test_collection"]
                query = test_collection.find({}, {"release_name": 1})
                assert query[0]["release_name"] == "Focal Fossa"

    except RetryError:
        assert False, "Newly added unit doesn't replicate data."

    client.close()

    # TODO in a future PR implement: newly removed members are gone without data.
