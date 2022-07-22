#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os

import pytest
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.ha_tests.helpers import (
    APP_NAME,
    UNIT_IDS,
    fetch_replica_set_members,
    find_unit,
    get_password,
    replica_set_client,
    replica_set_primary,
    unit_uri,
)

logger = logging.getLogger(__name__)

ANOTHER_DATABASE_APP_NAME = "another-database-a"


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


async def test_replication_across_members(ops_test: OpsTest) -> None:
    """Check consistency, ie write to primary, read data from secondaries."""
    # first find primary, write to primary, then read from each unit
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[APP_NAME].units]
    primary = await replica_set_primary(ip_addresses, ops_test)
    password = await get_password(ops_test)
    client = MongoClient(unit_uri(primary, password), directConnection=True)

    db = client["new-db"]
    test_collection = db["test_collection"]
    ubuntu = {"release_name": "Focal Fossa", "version": 20.04, "LTS": True}
    test_collection.insert(ubuntu)

    client.close()

    secondaries = set(ip_addresses) - set([primary])
    logger.error(secondaries)
    for secondary in secondaries:
        client = MongoClient(unit_uri(secondary, password), directConnection=True)

        db = client["new-db"]
        test_collection = db["test_collection"]
        query = test_collection.find({}, {"release_name": 1})
        logger.error(query[0]["release_name"])
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
    ubuntu = {"release_name": "Jammy Jelly", "version": 22.04, "LTS": False}
    test_collection.insert(ubuntu)

    # read all entries from new cluster
    cursor = test_collection.find({})
    cluster_1_entries = set()
    for document in cursor:
        logger.error(document)
        cluster_1_entries.add(document["release_name"])

    client.close()

    # read all entries from other cluster
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[APP_NAME].units]
    password = await get_password(ops_test)
    client = replica_set_client(ip_addresses, password)

    db = client["new-db"]
    test_collection = db["test_collection"]

    # read all entries from original cluster
    cursor = test_collection.find({})
    cluster_2_entries = set()
    for document in cursor:
        cluster_2_entries.add(document["release_name"])

    client.close()

    common_entries = cluster_2_entries.intersection(cluster_1_entries)
    logger.error(cluster_1_entries)
    logger.error(cluster_2_entries)
    assert len(common_entries) == 0, "Writes from one cluster are replicated to another cluster."


async def test_replication_member_scaling(ops_test: OpsTest) -> None:
    """Verify newly added and newly removed members properly replica data.

    Verify newly members have replicated data and newly removed members are gone without data.
    """
    original_ip_addresses = [
        unit.public_address for unit in ops_test.model.applications[APP_NAME].units
    ]
    await ops_test.model.applications[APP_NAME].add_unit(count=1)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)
    assert len(ops_test.model.applications[APP_NAME].units) == 4

    new_ip_addresses = [
        unit.public_address for unit in ops_test.model.applications[APP_NAME].units
    ]
    new_member_ip = list(set(new_ip_addresses) - set(original_ip_addresses))[0]
    password = await get_password(ops_test)
    client = MongoClient(unit_uri(new_member_ip, password), directConnection=True)

    # check for replicated data while retrying to give time for replica to copy over data.
    try:
        for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(3)):
            with attempt:
                db = client["new-db"]
                test_collection = db["test_collection"]
                query = test_collection.find({}, {"release_name": 1})
                logger.error(query[0]["release_name"])
                assert query[0]["release_name"] == "Focal Fossa"

    except RetryError:
        assert False, "Newly added unit doesn't replicate data."

    client.close()

    # TODO in a future PR implement: newly removed members are gone without data.
    # TODO in a future PR implement: a test that option "preserves data on delete" works
    # Note for above tests it will be necessary to test on a different substrate (ie AWS) see:
    # https://chat.canonical.com/canonical/pl/eirmfogfx3rmufmom9thjx6pwr
