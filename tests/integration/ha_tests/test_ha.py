#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import asyncio
import time

import pytest
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.ha_tests.helpers import (
    APP_NAME,
    add_unit_with_storage,
    all_db_processes_down,
    app_name,
    clear_db_writes,
    count_primaries,
    count_writes,
    fetch_replica_set_members,
    find_unit,
    get_password,
    insert_focal_to_cluster,
    kill_unit_process,
    mongod_ready,
    replica_set_client,
    replica_set_primary,
    retrieve_entries,
    reused_storage,
    secondary_up_to_date,
    start_continous_writes,
    stop_continous_writes,
    storage_id,
    storage_type,
    unit_uri,
    update_restart_delay,
    verify_replica_set_configuration,
)

ANOTHER_DATABASE_APP_NAME = "another-database-a"
MONGOD_PROCESS = "/usr/bin/mongod"
MEDIAN_REELECTION_TIME = 12
RESTART_DELAY = 60 * 3
ORIGINAL_RESTART_DELAY = 5


@pytest.fixture()
async def continuous_writes(ops_test: OpsTest):
    """Starts continuous write operations to MongoDB for test and clears writes at end of test."""
    await start_continous_writes(ops_test, 1)
    yield
    await clear_db_writes(ops_test)


@pytest.fixture()
async def reset_restart_delay(ops_test: OpsTest):
    """Resets service file delay on all units."""
    yield
    app = await app_name(ops_test)
    for unit in ops_test.model.applications[app].units:
        await update_restart_delay(ops_test, unit, ORIGINAL_RESTART_DELAY)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for HA testing. Hence check if there
    # is a pre-existing cluster.
    if await app_name(ops_test):
        return

    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=3)
    await ops_test.model.wait_for_idle()


async def test_storage_re_use(ops_test, continuous_writes):
    """Verifies that database units with attached storage correctly repurpose storage.

    It is not enough to verify that Juju attaches the storage. Hence test checks that the mongod
    properly uses the storage that was provided. (ie. doesn't just re-sync everything from
    primary, but instead computes a diff between current storage and primary storage.)
    """
    app = await app_name(ops_test)
    if storage_type(ops_test, app) == "rootfs":
        pytest.skip(
            "re-use of storage can only be used on deployments with persistent storage not on rootfs deployments"
        )

    # removing the only replica can be disastrous
    if len(ops_test.model.applications[app].units) < 2:
        await ops_test.model.applications[app].add_unit(count=1)
        await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=1000)

    # remove a unit and attach it's storage to a new unit
    unit = ops_test.model.applications[app].units[0]
    unit_storage_id = storage_id(ops_test, unit.name)
    expected_units = len(ops_test.model.applications[app].units) - 1
    removal_time = time.time()
    await ops_test.model.destroy_unit(unit.name)
    await ops_test.model.wait_for_idle(
        apps=[app], status="active", timeout=1000, wait_for_exact_units=expected_units
    )
    new_unit = await add_unit_with_storage(ops_test, app, unit_storage_id)

    assert await reused_storage(
        ops_test, new_unit.public_address, removal_time
    ), "attached storage not properly re-used by MongoDB."

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.abort_on_fail
async def test_add_units(ops_test: OpsTest, continuous_writes) -> None:
    """Tests juju add-unit functionality.

    Verifies that when a new unit is added to the MongoDB application that it is added to the
    MongoDB replica set configuration.
    """
    # add units and wait for idle
    app = await app_name(ops_test)
    expected_units = len(ops_test.model.applications[app].units) + 2
    await ops_test.model.applications[app].add_unit(count=2)
    await ops_test.model.wait_for_idle(
        apps=[app], status="active", timeout=1000, wait_for_exact_units=expected_units
    )

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]

    # connect to replica set uri and get replica set members
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test)

    # verify that the replica set members have the correct units
    assert set(member_ips) == set(ip_addresses)

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.abort_on_fail
async def test_scale_down_capablities(ops_test: OpsTest, continuous_writes) -> None:
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
    expected_units = len(ops_test.model.applications[app].units) - len(units_to_remove)
    await ops_test.model.destroy_units(*units_to_remove)

    # wait for app to be active after removal of units
    await ops_test.model.wait_for_idle(
        apps=[app], status="active", timeout=1000, wait_for_exact_units=expected_units
    )

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

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes


async def test_replication_across_members(ops_test: OpsTest, continuous_writes) -> None:
    """Check consistency, ie write to primary, read data from secondaries."""
    # first find primary, write to primary, then read from each unit
    await insert_focal_to_cluster(ops_test)
    app = await app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    primary = await replica_set_primary(ip_addresses, ops_test)
    password = await get_password(ops_test, app)

    secondaries = set(ip_addresses) - set([primary])
    for secondary in secondaries:
        client = MongoClient(unit_uri(secondary, password, app), directConnection=True)

        db = client["new-db"]
        test_collection = db["test_ubuntu_collection"]
        query = test_collection.find({}, {"release_name": 1})
        assert query[0]["release_name"] == "Focal Fossa"

        client.close()

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes


async def test_unique_cluster_dbs(ops_test: OpsTest, continuous_writes) -> None:
    """Verify unique clusters do not share DBs."""
    # first find primary, write to primary,
    await insert_focal_to_cluster(ops_test)

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
    test_collection = db["test_ubuntu_collection"]
    test_collection.insert({"release_name": "Jammy Jelly", "version": 22.04, "LTS": False})
    client.close()

    cluster_1_entries = await retrieve_entries(
        ops_test,
        app=ANOTHER_DATABASE_APP_NAME,
        db_name="new-db",
        collection_name="test_ubuntu_collection",
        query_field="release_name",
    )

    cluster_2_entries = await retrieve_entries(
        ops_test,
        app=APP_NAME,
        db_name="new-db",
        collection_name="test_ubuntu_collection",
        query_field="release_name",
    )

    common_entries = cluster_2_entries.intersection(cluster_1_entries)
    assert len(common_entries) == 0, "Writes from one cluster are replicated to another cluster."

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes


async def test_replication_member_scaling(ops_test: OpsTest, continuous_writes) -> None:
    """Verify newly added and newly removed members properly replica data.

    Verify newly members have replicated data and newly removed members are gone without data.
    """
    # first find primary, write to primary,
    await insert_focal_to_cluster(ops_test)

    app = await app_name(ops_test)
    original_ip_addresses = [
        unit.public_address for unit in ops_test.model.applications[app].units
    ]
    expected_units = len(ops_test.model.applications[app].units) + 1
    await ops_test.model.applications[app].add_unit(count=1)
    await ops_test.model.wait_for_idle(
        apps=[app], status="active", timeout=1000, wait_for_exact_units=expected_units
    )

    new_ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    new_member_ip = list(set(new_ip_addresses) - set(original_ip_addresses))[0]
    password = await get_password(ops_test, app)
    client = MongoClient(unit_uri(new_member_ip, password, app), directConnection=True)

    # check for replicated data while retrying to give time for replica to copy over data.
    try:
        for attempt in Retrying(stop=stop_after_delay(2 * 60), wait=wait_fixed(3)):
            with attempt:
                db = client["new-db"]
                test_collection = db["test_ubuntu_collection"]
                query = test_collection.find({}, {"release_name": 1})
                assert query[0]["release_name"] == "Focal Fossa"

    except RetryError:
        assert False, "Newly added unit doesn't replicate data."

    client.close()

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes

    # TODO in a future PR implement: newly removed members are gone without data.


async def test_kill_db_process(ops_test, continuous_writes):
    # locate primary unit
    app = await app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    primary_name = await replica_set_primary(ip_addresses, ops_test, return_name=True)
    primary_ip = await replica_set_primary(ip_addresses, ops_test)

    await kill_unit_process(ops_test, primary_name, kill_code="SIGKILL")

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test)
    time.sleep(5)
    more_writes = await count_writes(ops_test)
    assert more_writes > writes, "writes not continuing to DB"

    # sleep for twice the median election time
    time.sleep(MEDIAN_REELECTION_TIME * 2)

    # verify that db service got restarted and is ready
    assert await mongod_ready(ops_test, primary_ip)

    # verify that a new primary gets elected (ie old primary is secondary)
    new_primary_name = await replica_set_primary(ip_addresses, ops_test, return_name=True)
    assert new_primary_name != primary_name

    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes, "writes to the db were missed."

    # verify that old primary is up to date.
    assert await secondary_up_to_date(
        ops_test, primary_ip, total_expected_writes["number"]
    ), "secondary not up to date with the cluster after restarting."


async def test_freeze_db_process(ops_test, continuous_writes):
    # locate primary unit
    app = await app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    primary_name = await replica_set_primary(ip_addresses, ops_test, return_name=True)
    primary_ip = await replica_set_primary(ip_addresses, ops_test)
    await kill_unit_process(ops_test, primary_name, kill_code="SIGSTOP")

    # sleep for twice the median election time
    time.sleep(MEDIAN_REELECTION_TIME * 2)

    # verify that a new primary gets elected
    new_primary_name = await replica_set_primary(ip_addresses, ops_test, return_name=True)
    assert new_primary_name != primary_name

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test)
    time.sleep(5)
    more_writes = await count_writes(ops_test)

    # un-freeze the old primary
    await kill_unit_process(ops_test, primary_name, kill_code="SIGCONT")

    # check this after un-freezing the old primary so that if this check fails we still "turned
    # back on" the mongod process
    assert more_writes > writes, "writes not continuing to DB"

    # verify that db service got restarted and is ready
    assert await mongod_ready(ops_test, primary_ip)

    # verify all units are running under the same replset
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test)
    assert set(member_ips) == set(ip_addresses), "all members not running under the same replset"

    # verify there is only one primary after un-freezing old primary
    assert (
        await count_primaries(ops_test) == 1
    ), "there are more than one primary in the replica set."

    # verify that the old primary does not "reclaim" primary status after un-freezing old primary
    new_primary_name = await replica_set_primary(ip_addresses, ops_test, return_name=True)
    assert new_primary_name != primary_name, "un-frozen primary should be secondary."

    # verify that no writes were missed.
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert actual_writes == total_expected_writes["number"], "db writes missing."

    # verify that old primary is up to date.
    assert await secondary_up_to_date(
        ops_test, primary_ip, actual_writes
    ), "secondary not up to date with the cluster after restarting."


async def test_restart_db_process(ops_test, continuous_writes):
    # locate primary unit
    app = await app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    primary_name = await replica_set_primary(ip_addresses, ops_test, return_name=True)
    primary_ip = await replica_set_primary(ip_addresses, ops_test)

    # send SIGTERM, we expect `systemd` to restart the process
    await kill_unit_process(ops_test, primary_name, kill_code="SIGTERM")

    # TODO (future PR): find a reliable way to verify db step down, current implementation uses
    # mongodb logs which rotate too quickly and leave us unable to verify the db step down
    # processes success.
    # # verify that a stepdown was performed on restart. SIGTERM should send a graceful restart and
    # # send a replica step down signal.
    # assert await db_step_down(
    #     ops_test, primary_ip, sig_term_time
    # ), "old primary departed without stepping down."

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test)
    time.sleep(5)
    more_writes = await count_writes(ops_test)
    assert more_writes > writes, "writes not continuing to DB"

    # verify that db service got restarted and is ready
    assert await mongod_ready(ops_test, primary_ip)

    # verify that a new primary gets elected (ie old primary is secondary)
    new_primary_name = await replica_set_primary(ip_addresses, ops_test, return_name=True)
    assert new_primary_name != primary_name

    # verify that no writes were missed
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes

    # verify that old primary is up to date.
    assert await secondary_up_to_date(
        ops_test, primary_ip, total_expected_writes["number"]
    ), "secondary not up to date with the cluster after restarting."


async def test_full_cluster_crash(ops_test: OpsTest, continuous_writes, reset_restart_delay):
    app = await app_name(ops_test)

    # update all units to have a new RESTART_DELAY,  Modifying the Restart delay to 3 minutes
    # should ensure enough time for all replicas to be down at the same time.
    for unit in ops_test.model.applications[app].units:
        await update_restart_delay(ops_test, unit, RESTART_DELAY)

    # kill all units "simulatenously"
    await asyncio.gather(
        *[
            kill_unit_process(ops_test, unit.name, kill_code="SIGKILL")
            for unit in ops_test.model.applications[app].units
        ]
    )

    # This test serves to verify behavior when all replicas are down at the same time that when
    # they come back online they operate as expected. This check verfies that we meet the criterea
    # of all replicas being down at the same time.
    assert await all_db_processes_down(ops_test), "Not all units down at the same time."

    # sleep for twice the median election time and the restart delay
    time.sleep(MEDIAN_REELECTION_TIME * 2 + RESTART_DELAY)

    # verify all units are up and running
    for unit in ops_test.model.applications[app].units:
        assert await mongod_ready(
            ops_test, unit.public_address
        ), f"unit {unit.name} not restarted after cluster crash."

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test)
    time.sleep(5)
    more_writes = await count_writes(ops_test)
    assert more_writes > writes, "writes not continuing to DB"

    # verify presence of primary, replica set member configuration, and number of primaries
    await verify_replica_set_configuration(ops_test)

    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)

    # verify that no writes were missed.
    assert actual_writes == total_expected_writes["number"], "db writes missing."


async def test_full_cluster_restart(ops_test: OpsTest, continuous_writes, reset_restart_delay):
    app = await app_name(ops_test)

    # update all units to have a new RESTART_DELAY,  Modifying the Restart delay to 3 minutes
    # should ensure enough time for all replicas to be down at the same time.
    for unit in ops_test.model.applications[app].units:
        await update_restart_delay(ops_test, unit, RESTART_DELAY)

    # kill all units "simulatenously"
    await asyncio.gather(
        *[
            kill_unit_process(ops_test, unit.name, kill_code="SIGTERM")
            for unit in ops_test.model.applications[app].units
        ]
    )

    # This test serves to verify behavior when all replicas are down at the same time that when
    # they come back online they operate as expected. This check verfies that we meet the criterea
    # of all replicas being down at the same time.
    assert await all_db_processes_down(ops_test), "Not all units down at the same time."

    # sleep for twice the median election time and the restart delay
    time.sleep(MEDIAN_REELECTION_TIME * 2 + RESTART_DELAY)

    # verify all units are up and running
    for unit in ops_test.model.applications[app].units:
        assert await mongod_ready(
            ops_test, unit.public_address
        ), f"unit {unit.name} not restarted after cluster crash."

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test)
    time.sleep(5)
    more_writes = await count_writes(ops_test)
    assert more_writes > writes, "writes not continuing to DB"

    # verify presence of primary, replica set member configuration, and number of primaries
    await verify_replica_set_configuration(ops_test)

    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test)
    assert total_expected_writes["number"] == actual_writes, "writes to the db were missed."
