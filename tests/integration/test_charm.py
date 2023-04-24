#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import subprocess
import time

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from pytest_operator.plugin import OpsTest
from tenacity import RetryError

from .ha_tests.helpers import app_name, kill_unit_process
from .helpers import (
    APP_NAME,
    PORT,
    UNIT_IDS,
    count_primaries,
    find_unit,
    get_password,
    unit_uri,
)

logger = logging.getLogger(__name__)

ANOTHER_DATABASE_APP_NAME = "another-database-a"

MEDIAN_REELECTION_TIME = 12


@pytest.mark.skipif(
    os.environ.get("PYTEST_SKIP_DEPLOY", False),
    reason="skipping deploy, model expected to be provided.",
)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    model_name = ops_test.model.info.name
    subprocess.check_output(
        f"juju set-model-constraints --model={model_name} cores=2 mem=1G".split()
    )

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
    client = MongoClient(connection, replicaset="mongodb")

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


async def test_set_password_action(ops_test: OpsTest) -> None:
    """Tests that action set-password outputs resets the password on app data and mongod."""
    # verify that password is correctly rotated by comparing old password with rotated one.
    old_password = await get_password(ops_test)
    unit = await find_unit(ops_test, leader=True)
    action = await unit.run_action("set-password")
    action = await action.wait()
    new_password = action.results["password"]
    assert new_password != old_password
    new_password_reported = await get_password(ops_test)
    assert new_password == new_password_reported

    # verify that the password is updated in mongod by inserting into the collection.
    try:
        client = MongoClient(unit_uri(unit.public_address, new_password), directConnection=True)
        client["new-db"].list_collection_names()
    except PyMongoError as e:
        assert False, f"Failed to access collection with new password, error: {e}"
    finally:
        client.close()

    # perform the same tests as above but with a user provided password.
    old_password = await get_password(ops_test)
    action = await unit.run_action("set-password", **{"password": "safe_pass"})
    action = await action.wait()
    new_password = action.results["password"]
    assert new_password != old_password
    new_password_reported = await get_password(ops_test)
    assert "safe_pass" == new_password_reported

    # verify that the password is updated in mongod by inserting into the collection.
    try:
        client = MongoClient(unit_uri(unit.public_address, "safe_pass"), directConnection=True)
        client["new-db"].list_collection_names()
    except PyMongoError as e:
        assert False, f"Failed to access collection with new password, error: {e}"
    finally:
        client.close()


async def test_monitor_user(ops_test: OpsTest) -> None:
    """Test verifies that the monitor user can perform operations such as 'rs.conf()'."""
    unit = ops_test.model.applications[APP_NAME].units[0]
    password = await get_password(ops_test, "mongodb", "monitor")
    replica_set_hosts = [
        unit.public_address for unit in ops_test.model.applications["mongodb"].units
    ]
    hosts = ",".join(replica_set_hosts)
    replica_set_uri = f"mongodb://monitor:{password}@{hosts}/admin?replicaSet=mongodb"

    admin_mongod_cmd = f"charmed-mongodb.mongo '{replica_set_uri}'  --eval 'rs.conf()'"
    check_monitor_cmd = f"run --unit {unit.name} -- {admin_mongod_cmd}"
    return_code, _, _ = await ops_test.juju(*check_monitor_cmd.split())
    assert return_code == 0, "command rs.conf() on monitor user does not work"


async def test_exactly_one_primary_reported_by_juju(ops_test: OpsTest) -> None:
    """Tests that there is exactly one replica set primary unit reported by juju."""

    async def get_unit_messages():
        """Collects unit status messages."""
        app = await app_name(ops_test)
        unit_messages = {}

        async with ops_test.fast_forward():
            time.sleep(20)

        for unit in ops_test.model.applications[app].units:
            unit_messages[unit.entity_id] = unit.workload_status_message

        return unit_messages

    def juju_reports_one_primary(unit_messages):
        """Confirms there is only one replica set primary unit reported by juju."""
        count = 0
        for value in unit_messages:
            if unit_messages[value] == "Replica set primary":
                count += 1

        assert count == 1, f"Juju is expected to report one primary not {count} primaries"

    # collect unit status messages
    unit_messages = await get_unit_messages()

    # confirm there is only one replica set primary unit
    juju_reports_one_primary(unit_messages)

    # kill the mongod process on the replica set primary unit to force a re-election
    for unit, message in unit_messages.items():
        if message == "Replica set primary":
            target_unit = unit

    await kill_unit_process(ops_test, target_unit, kill_code="SIGKILL")

    # wait for re-election, sleep for twice the median election time
    time.sleep(MEDIAN_REELECTION_TIME * 2)

    # collect unit status messages
    unit_messages = await get_unit_messages()

    # confirm there is only one replica set primary unit
    juju_reports_one_primary(unit_messages)

    # cleanup, remove killed unit
    await ops_test.model.destroy_unit(target_unit)
