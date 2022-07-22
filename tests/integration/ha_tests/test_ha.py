#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
from re import U
from xml.etree.ElementPath import ops

import pytest
from helpers import (
    APP_NAME,
    fetch_replica_set_members,
    find_unit,
    replica_set_primary,
    unit_ids,
    ha_on_provided_cluster,
)
from pytest_operator.plugin import OpsTest
from tenacity import RetryError

logger = logging.getLogger(__name__)


""" TODO LIST 
1. update UNIT_IDS to be a function, this function returns UNIT_IDS if being deployed on a fresh
   cluster. Otherwise it returns the number of units in the pre-existing deployed cluster.

"""


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for HA testing
    if await ha_on_provided_cluster(ops_test):
        return

    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=len(unit_ids(ops_test)))
    await ops_test.model.wait_for_idle()


@pytest.mark.abort_on_fail
async def test_add_units(ops_test: OpsTest) -> None:
    """Tests juju add-unit functionality.

    Verifies that when a new unit is added to the MongoDB application that it is added to the
    MongoDB replica set configuration.
    """
    # add units and wait for idle
    await ops_test.model.applications[APP_NAME].add_unit(count=2)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=1000)
    assert len(ops_test.model.applications[APP_NAME].units) == len(unit_ids(ops_test)) + 2

    # grab unit ips
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[APP_NAME].units]

    # connect to replica set uri and get replica set members
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test)

    # verify that the replica set members have the correct units
    assert set(member_ips) == set(ip_addresses)


@pytest.mark.abort_on_fail
async def test_scale_down_capablities(ops_test: OpsTest) -> None:
    """Tests clusters behavior when scaling down a minority and removing a primary replica.

    TODO
    - make app name a function
    - NOTE: on a provided cluster this calculate the largest set of minority members and removes
    them, the primary is gaurenteed to be one of those minority members.

    This test verifies that the behavior of:
    1.  when a leader is deleted that the new leader, on calling leader_elected will reconfigure
    the replicaset.
    2. primary stepping down leads to a replica set with a new primary.
    3. removing a minority of units (2 out of 5) is feasiable.
    4. race conditions due to removing multiple units is handled.
    5. deleting a non-leader unit is properly handled.
    """
    deleted_unit_ips = []
    # units_to_remove = []
    # minority_count = int(len(ops_test.model.applications[APP_NAME].units) / 2)

    # find leader unit
    leader_unit = await find_unit(ops_test, leader=True)
    # minority_count -= 1

    # verify that we have a leader
    assert leader_unit is not None, "No unit is leader"
    deleted_unit_ips.append(leader_unit.public_address)
    # units_to_remove.append(leader_unit.name)

    # avail_units = [unit for unit in ops_test.model.applications[APP_NAME]]
    # avail_units.remove(leader_unit)
    # for i in range(minority_count):
    #     pass

    # find non-leader unit
    non_leader_unit = await find_unit(ops_test, leader=False)
    deleted_unit_ips.append(non_leader_unit.public_address)

    # destroy 2 units simulatenously
    # pass a lambda function here.
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
