#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
import os
import time

import pytest
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from ..helpers import (
    check_or_scale_app,
    get_app_name,
    get_unit_ip,
    instance_ip,
    unit_hostname,
    unit_uri,
)
from .helpers import (
    all_db_processes_down,
    count_primaries,
    count_writes,
    cut_network_from_unit,
    db_step_down,
    fetch_replica_set_members,
    find_unit,
    get_controller_machine,
    get_password,
    insert_focal_to_cluster,
    is_machine_reachable_from,
    kill_unit_process,
    mongod_ready,
    replica_set_client,
    replica_set_primary,
    restore_network_for_unit,
    retrieve_entries,
    scale_and_verify,
    secondary_up_to_date,
    stop_continous_writes,
    update_restart_delay,
    verify_replica_set_configuration,
    verify_writes,
    wait_network_restore,
)

ANOTHER_DATABASE_APP_NAME = "another-database-a"
MEDIAN_REELECTION_TIME = 12
RESTART_DELAY = 60 * 3
logger = logging.getLogger(__name__)


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.skipif(
    os.environ.get("PYTEST_SKIP_DEPLOY", False),
    reason="skipping deploy, model expected to be provided.",
)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for HA testing. Hence check if there
    # is a pre-existing cluster.
    required_units = 3
    user_app_name = await get_app_name(ops_test)
    if user_app_name:
        await check_or_scale_app(ops_test, user_app_name, required_units)
        return

    my_charm = await ops_test.build_charm(".")

    storage = {"mongodb": {"pool": "lxd", "size": 2048}}

    await ops_test.model.deploy(my_charm, num_units=required_units, storage=storage)
    await ops_test.model.wait_for_idle()


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_add_units(ops_test: OpsTest, continuous_writes) -> None:
    """Tests juju add-unit functionality.

    Verifies that when a new unit is added to the MongoDB application that it is added to the
    MongoDB replica set configuration.
    """
    # add units and wait for idle
    app_name = await get_app_name(ops_test)
    expected_units = len(ops_test.model.applications[app_name].units) + 2
    await ops_test.model.applications[app_name].add_unit(count=2)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, wait_for_exact_units=expected_units
    )

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]

    # connect to replica set uri and get replica set members
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test, app_name=app_name)

    # verify that the replica set members have the correct units
    assert set(member_ips) == set(ip_addresses)

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
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
    app_name = await get_app_name(ops_test)
    units_to_remove = []
    minority_count = int(len(ops_test.model.applications[app_name].units) / 2)

    # find leader unit
    leader_unit = await find_unit(ops_test, leader=True, app_name=app_name)
    minority_count -= 1

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"
    deleted_unit_ips.append(leader_unit.public_address)
    units_to_remove.append(leader_unit.name)

    # find non-leader units to remove such that the largest minority possible is removed.
    avail_units = []
    for unit in ops_test.model.applications[app_name].units:
        if not unit.name == leader_unit.name:
            avail_units.append(unit)

    for _ in range(minority_count):
        unit_to_remove = avail_units.pop()
        deleted_unit_ips.append(unit_to_remove.public_address)
        units_to_remove.append(unit_to_remove.name)

    # destroy units simultaneously
    expected_units = len(ops_test.model.applications[app_name].units) - len(units_to_remove)
    await ops_test.model.destroy_units(*units_to_remove)

    # wait for app to be active after removal of units
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, wait_for_exact_units=expected_units
    )

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]

    # check that the replica set with the remaining units has a primary
    try:
        primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    except RetryError:
        primary = None

    # verify that the primary is not None
    assert primary is not None, "replica set has no primary"

    # check that the primary is one of the remaining units
    assert (
        primary.public_address in ip_addresses
    ), "replica set primary is not one of the available units"

    # verify that the configuration of mongodb no longer has the deleted ip
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test, app_name=app_name)

    assert set(member_ips) == set(ip_addresses), "mongod config contains deleted units"

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_replication_across_members(ops_test: OpsTest, continuous_writes) -> None:
    """Check consistency, ie write to primary, read data from secondaries."""
    # first find primary, write to primary, then read from each unit
    await insert_focal_to_cluster(ops_test)
    app_name = await get_app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    password = await get_password(ops_test, app_name)

    secondaries = set(ip_addresses) - {primary.public_address}
    for secondary in secondaries:
        client = MongoClient(unit_uri(secondary, password, app_name), directConnection=True)

        db = client["new-db"]
        test_collection = db["test_ubuntu_collection"]
        query = test_collection.find({}, {"release_name": 1})
        assert query[0]["release_name"] == "Focal Fossa"

        client.close()

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_unique_cluster_dbs(ops_test: OpsTest, continuous_writes) -> None:
    """Verify unique clusters do not share DBs."""
    # first find primary, write to primary,
    app_name = await get_app_name(ops_test)
    await insert_focal_to_cluster(ops_test, app_name=app_name)

    # deploy new cluster
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=1, application_name=ANOTHER_DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle(apps=[ANOTHER_DATABASE_APP_NAME], status="active")

    # write data to new cluster
    ip_addresses = [
        unit.public_address
        for unit in ops_test.model.applications[ANOTHER_DATABASE_APP_NAME].units
    ]
    password = await get_password(ops_test, app_name=ANOTHER_DATABASE_APP_NAME)
    client = replica_set_client(ip_addresses, password, app_name=ANOTHER_DATABASE_APP_NAME)
    db = client["new-db"]
    test_collection = db["test_ubuntu_collection"]
    test_collection.insert_one({"release_name": "Jammy Jelly", "version": 22.04, "LTS": False})
    client.close()

    cluster_1_entries = await retrieve_entries(
        ops_test,
        app_name=ANOTHER_DATABASE_APP_NAME,
        db_name="new-db",
        collection_name="test_ubuntu_collection",
        query_field="release_name",
    )

    cluster_2_entries = await retrieve_entries(
        ops_test,
        app_name=app_name,
        db_name="new-db",
        collection_name="test_ubuntu_collection",
        query_field="release_name",
    )

    common_entries = cluster_2_entries.intersection(cluster_1_entries)
    assert len(common_entries) == 0, "Writes from one cluster are replicated to another cluster."

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_replication_member_scaling(ops_test: OpsTest, continuous_writes) -> None:
    """Verify newly added and newly removed members properly replica data.

    Verify newly members have replicated data and newly removed members are gone without data.
    """
    app_name = await get_app_name(ops_test)

    # first find primary, write to primary,
    await insert_focal_to_cluster(ops_test, app_name=app_name)
    original_ip_addresses = [
        unit.public_address for unit in ops_test.model.applications[app_name].units
    ]
    expected_units = len(ops_test.model.applications[app_name].units) + 1
    await ops_test.model.applications[app_name].add_unit(count=1)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=1000, wait_for_exact_units=expected_units
    )

    new_ip_addresses = [
        unit.public_address for unit in ops_test.model.applications[app_name].units
    ]
    new_member_ip = list(set(new_ip_addresses) - set(original_ip_addresses))[0]
    password = await get_password(ops_test, app_name)
    client = MongoClient(unit_uri(new_member_ip, password, app_name), directConnection=True)

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
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_kill_db_process(ops_test, continuous_writes):
    # locate primary unit
    app_name = await get_app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)

    await kill_unit_process(ops_test, primary.name, kill_code="SIGKILL", app_name=app_name)

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test, app_name=app_name)
    time.sleep(5)
    more_writes = await count_writes(ops_test, app_name=app_name)
    assert more_writes > writes, "writes not continuing to DB"

    # sleep for twice the median election time
    time.sleep(MEDIAN_REELECTION_TIME * 2)

    # verify that db service got restarted and is ready
    assert await mongod_ready(ops_test, primary.public_address, app_name=app_name)

    # verify that a new primary gets elected (ie old primary is secondary)
    new_primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    assert new_primary.name != primary.name

    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes, "writes to the db were missed."

    # verify that old primary is up to date.
    assert await secondary_up_to_date(
        ops_test, primary.public_address, total_expected_writes["number"], app_name=app_name
    ), "secondary not up to date with the cluster after restarting."


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_freeze_db_process(ops_test, continuous_writes):
    # locate primary unit
    app_name = await get_app_name(ops_test)
    password = await get_password(ops_test, app_name)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    await kill_unit_process(ops_test, primary.name, kill_code="SIGSTOP", app_name=app_name)

    # sleep for twice the median election time
    time.sleep(MEDIAN_REELECTION_TIME * 2)

    # verify that a new primary gets elected
    new_primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    assert new_primary.name != primary.name

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test, app_name=app_name)
    time.sleep(5)
    more_writes = await count_writes(ops_test, app_name=app_name)
    # un-freeze the old primary
    await kill_unit_process(ops_test, primary.name, kill_code="SIGCONT", app_name=app_name)

    # check this after un-freezing the old primary so that if this check fails we still "turned
    # back on" the mongod process
    assert more_writes > writes, "writes not continuing to DB"

    # verify that db service got restarted and is ready
    assert await mongod_ready(ops_test, primary.public_address, app_name=app_name)

    # verify all units are running under the same replset
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test, app_name=app_name)
    assert set(member_ips) == set(ip_addresses), "all members not running under the same replset"

    # verify there is only one primary after un-freezing old primary
    assert (
        await count_primaries(ops_test, password=password, app_name=app_name) == 1
    ), "there are more than one primary in the replica set."

    # verify that the old primary does not "reclaim" primary status after un-freezing old primary
    new_primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    assert new_primary.name != primary.name, "un-frozen primary should be secondary."

    # verify that no writes were missed.
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert actual_writes == total_expected_writes["number"], "db writes missing."
    # verify that old primary is up to date.
    assert await secondary_up_to_date(
        ops_test, primary.public_address, actual_writes, app_name=app_name
    ), "secondary not up to date with the cluster after restarting."


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_restart_db_process(ops_test, continuous_writes):
    # locate primary unit
    app_name = await get_app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    old_primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)

    # send SIGTERM, we expect `systemd` to restart the process
    sig_term_time = time.time()
    await kill_unit_process(ops_test, old_primary.name, kill_code="SIGTERM", app_name=app_name)

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test, app_name=app_name)
    time.sleep(5)
    more_writes = await count_writes(ops_test, app_name=app_name)
    assert more_writes > writes, "writes not continuing to DB"

    # verify that db service got restarted and is ready
    assert await mongod_ready(ops_test, old_primary.public_address, app_name=app_name)

    # verify that a new primary gets elected (ie old primary is secondary)
    new_primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    assert new_primary.name != old_primary.name

    # verify that a stepdown was performed on restart. SIGTERM should send a graceful restart and
    # send a replica step down signal. Performed with a retry to give time for the logs to update.
    try:
        for attempt in Retrying(stop=stop_after_delay(30), wait=wait_fixed(3)):
            with attempt:
                assert await db_step_down(
                    ops_test, old_primary.name, sig_term_time, app_name=app_name
                ), "old primary departed without stepping down."
    except RetryError:
        False, "old primary departed without stepping down."

    # verify that no writes were missed
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes

    # verify that old primary is up to date.
    assert await secondary_up_to_date(
        ops_test, old_primary.public_address, total_expected_writes["number"], app_name=app_name
    ), "secondary not up to date with the cluster after restarting."


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_full_cluster_crash(ops_test: OpsTest, continuous_writes, reset_restart_delay):
    app_name = await get_app_name(ops_test)

    # update all units to have a new RESTART_DELAY,  Modifying the Restart delay to 3 minutes
    # should ensure enough time for all replicas to be down at the same time.
    for unit in ops_test.model.applications[app_name].units:
        await update_restart_delay(ops_test, unit, RESTART_DELAY)

    # kill all units "simultaneously"
    await asyncio.gather(
        *[
            kill_unit_process(ops_test, unit.name, kill_code="SIGKILL", app_name=app_name)
            for unit in ops_test.model.applications[app_name].units
        ]
    )

    # This test serves to verify behavior when all replicas are down at the same time that when
    # they come back online they operate as expected. This check verifies that we meet the criteria
    # of all replicas being down at the same time.
    assert await all_db_processes_down(
        ops_test, app_name=app_name
    ), "Not all units down at the same time."

    # sleep for twice the median election time and the restart delay
    time.sleep(MEDIAN_REELECTION_TIME * 2 + RESTART_DELAY)

    # verify all units are up and running
    for unit in ops_test.model.applications[app_name].units:
        assert await mongod_ready(
            ops_test, unit.public_address, app_name=app_name
        ), f"unit {unit.name} not restarted after cluster crash."

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test, app_name=app_name)
    time.sleep(5)
    more_writes = await count_writes(ops_test, app_name=app_name)
    assert more_writes > writes, "writes not continuing to DB"

    # verify presence of primary, replica set member configuration, and number of primaries
    await verify_replica_set_configuration(ops_test, app_name=app_name)

    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)

    # verify that no writes were missed.
    assert actual_writes == total_expected_writes["number"], "db writes missing."


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_full_cluster_restart(ops_test: OpsTest, continuous_writes, reset_restart_delay):
    app_name = await get_app_name(ops_test)

    # update all units to have a new RESTART_DELAY,  Modifying the Restart delay to 3 minutes
    # should ensure enough time for all replicas to be down at the same time.
    for unit in ops_test.model.applications[app_name].units:
        await update_restart_delay(ops_test, unit, RESTART_DELAY)

    # kill all units "simultaneously"
    await asyncio.gather(
        *[
            kill_unit_process(ops_test, unit.name, kill_code="SIGTERM", app_name=app_name)
            for unit in ops_test.model.applications[app_name].units
        ]
    )

    # This test serves to verify behavior when all replicas are down at the same time that when
    # they come back online they operate as expected. This check verifies that we meet the criteria
    # of all replicas being down at the same time.
    assert await all_db_processes_down(
        ops_test, app_name=app_name
    ), "Not all units down at the same time."

    # sleep for twice the median election time and the restart delay
    time.sleep(MEDIAN_REELECTION_TIME * 2 + RESTART_DELAY)

    # verify all units are up and running
    for unit in ops_test.model.applications[app_name].units:
        assert await mongod_ready(
            ops_test, unit.public_address, app_name=app_name
        ), f"unit {unit.name} not restarted after cluster crash."

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test, app_name=app_name)
    time.sleep(5)
    more_writes = await count_writes(ops_test, app_name=app_name)
    assert more_writes > writes, "writes not continuing to DB"

    # verify presence of primary, replica set member configuration, and number of primaries
    await verify_replica_set_configuration(ops_test, app_name=app_name)

    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes, "writes to the db were missed."


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_network_cut(ops_test, continuous_writes):
    # locate primary unit
    app_name = await get_app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    primary = await replica_set_primary(ip_addresses, ops_test, app_name=app_name)
    all_units = ops_test.model.applications[app_name].units
    model_name = ops_test.model.info.name

    primary_hostname = await unit_hostname(ops_test, primary.name)
    primary_unit_ip = await get_unit_ip(ops_test, primary.name)

    # before cutting network verify that connection is possible
    assert await mongod_ready(
        ops_test, primary.public_address, app_name=app_name
    ), f"Connection to host {primary.public_address} is not possible"

    cut_network_from_unit(primary_hostname)

    # verify machine is not reachable from peer units
    for unit in set(all_units) - {primary}:
        hostname = await unit_hostname(ops_test, unit.name)
        assert not is_machine_reachable_from(
            hostname, primary_hostname
        ), "unit is reachable from peer"

    # verify machine is not reachable from controller
    controller = await get_controller_machine(ops_test)
    assert not is_machine_reachable_from(
        controller, primary_hostname
    ), "unit is reachable from controller"

    # sleep for twice the median election time
    time.sleep(MEDIAN_REELECTION_TIME * 2)

    # verify new writes are continuing by counting the number of writes before and after a 5 second
    # wait
    writes = await count_writes(ops_test, down_unit=primary.name, app_name=app_name)
    time.sleep(5)
    more_writes = await count_writes(ops_test, down_unit=primary.name, app_name=app_name)
    assert more_writes > writes, "writes not continuing to DB"

    # verify that a new primary got elected
    new_primary = await replica_set_primary(
        ip_addresses, ops_test, down_unit=primary.name, app_name=app_name
    )
    assert new_primary.name != primary.name

    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(
        ops_test, down_unit=primary.name, app_name=app_name
    )
    actual_writes = await count_writes(ops_test, down_unit=primary.name, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes, "writes to the db were missed."

    # restore network connectivity to old primary
    restore_network_for_unit(primary_hostname)

    # wait until network is reestablished for the unit
    wait_network_restore(model_name, primary_hostname, primary_unit_ip)

    # self healing is performed with update status hook
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

    # verify we have connection to the old primary
    new_ip = instance_ip(model_name, primary_hostname)
    assert await mongod_ready(
        ops_test, new_ip, app_name=app_name
    ), f"Connection to host {new_ip} is not possible"

    # verify presence of primary, replica set member configuration, and number of primaries
    await verify_replica_set_configuration(ops_test, app_name=app_name)

    # verify that old primary is up to date.
    assert await secondary_up_to_date(
        ops_test, new_ip, total_expected_writes["number"], app_name=app_name
    ), "secondary not up to date with the cluster after restarting."


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@pytest.mark.unstable
async def test_scale_up_down(ops_test: OpsTest, continuous_writes):
    """Scale up and down the application and verify the replica set is healthy."""
    scales = [3, -3, 4, -4, 5, -5, 6, -6, 7, -7]
    for count in scales:
        await scale_and_verify(ops_test, count=count)
    await verify_writes(ops_test)


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
@pytest.mark.unstable
async def test_scale_up_down_removing_leader(ops_test: OpsTest, continuous_writes):
    """Scale up and down the application and verify the replica set is healthy."""
    scales = [3, -3, 4, -4, 5, -5, 6, -6, 7, -7]
    for count in scales:
        await scale_and_verify(ops_test, count=count, remove_leader=True)
    await verify_writes(ops_test)
