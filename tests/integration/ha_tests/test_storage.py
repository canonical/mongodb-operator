#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import time

import pytest
from juju import tag
from pytest_operator.plugin import OpsTest

from ..helpers import check_or_scale_app, get_app_name
from .helpers import (
    APP_NAME,
    count_writes,
    reused_storage,
    stop_continous_writes,
    storage_id,
    storage_type,
)

OTHER_MONGODB_APP_NAME = "mongodb-new"
TIMEOUT = 1000


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, database_charm) -> None:
    """Build and deploy one unit of MongoDB."""
    # it is possible for users to provide their own cluster for HA testing. Hence check if there
    # is a pre-existing cluster.
    required_units = 3
    user_app_name = await get_app_name(ops_test)
    if user_app_name:
        await check_or_scale_app(ops_test, user_app_name, required_units)
        return

    storage = {"mongodb": {"pool": "lxd", "size": 2048}}

    await ops_test.model.deploy(
        database_charm, application_name=APP_NAME, num_units=required_units, storage=storage
    )
    await ops_test.model.wait_for_idle()


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_storage_re_use(ops_test, continuous_writes):
    """Verifies that database units with attached storage correctly repurpose storage.

    It is not enough to verify that Juju attaches the storage. Hence test checks that the mongod
    properly uses the storage that was provided. (ie. doesn't just re-sync everything from
    primary, but instead computes a diff between current storage and primary storage.)
    """
    app_name = await get_app_name(ops_test)
    if storage_type(ops_test, app_name) == "rootfs":
        pytest.skip(
            "reuse of storage can only be used on deployments with persistent storage not on rootfs deployments"
        )

    # remove a unit and attach it's storage to a new unit
    unit = ops_test.model.applications[app_name].units[0]
    unit_storage_id = storage_id(ops_test, unit.name)
    expected_units = len(ops_test.model.applications[app_name].units) - 1
    removal_time = time.time()
    await ops_test.model.destroy_unit(unit.name)
    await ops_test.model.wait_for_idle(
        apps=[app_name], status="active", timeout=TIMEOUT, wait_for_exact_units=expected_units
    )
    new_unit = (
        await ops_test.model.applications[app_name].add_unit(
            count=1, attach_storage=[tag.storage(unit_storage_id)]
        )
    )[0]

    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=TIMEOUT)

    assert await reused_storage(
        ops_test, new_unit.name, removal_time
    ), "attached storage not properly reused by MongoDB."

    # verify that the no writes were skipped
    total_expected_writes = await stop_continous_writes(ops_test, app_name=app_name)
    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert total_expected_writes["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_storage_re_use_after_scale_down_to_zero(ops_test: OpsTest, continuous_writes):
    """Tests that we can reuse storage after a scale down to zero.

    For that, we completely scale down to zero while keeping the storages,
    and then we add units back with storage reuse and check that the
    storage has been reused.
    """
    app_name = await get_app_name(ops_test)
    if storage_type(ops_test, app_name) == "rootfs":
        pytest.skip(
            "reuse of storage can only be used on deployments with persistent storage not on rootfs deployments"
        )

    writes_results = await stop_continous_writes(ops_test, app_name=app_name)
    unit_ids = [unit.name for unit in ops_test.model.applications[app_name].units]
    storage_ids = {}

    remaining_units = len(unit_ids)
    for unit_id in unit_ids:
        storage_ids[unit_id] = storage_id(ops_test, unit_id)
        await ops_test.model.applications[app_name].destroy_unit(unit_id)
        # Give some time to remove the unit. We don't use asyncio.sleep here to
        # leave time for each unit to be removed before removing the next one.
        # time.sleep(60)
        remaining_units -= 1
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=TIMEOUT,
            idle_period=20,
            wait_for_exact_units=remaining_units,
        )

    # Wait until all apps are cleaned up
    await ops_test.model.wait_for_idle(apps=[app_name], timeout=TIMEOUT, wait_for_exact_units=0)

    for unit_id in unit_ids:
        n_units = len(ops_test.model.applications[app_name].units)
        await ops_test.model.applications[app_name].add_unit(
            count=1, attach_storage=[tag.storage(storage_ids[unit_id])]
        )
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=TIMEOUT,
            idle_period=20,
            wait_for_exact_units=n_units + 1,
        )

    await ops_test.model.wait_for_idle(
        apps=[app_name],
        status="active",
        timeout=TIMEOUT,
        idle_period=20,
        wait_for_exact_units=len(unit_ids),
    )

    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert writes_results["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_storage_reuse_new_app_same_name(
    ops_test: OpsTest, database_charm, continuous_writes
):
    """Tests that we can reuse storage from a different cluster, with the same app name.

    For that, we completely remove the application while keeping the storages,
    and then we deploy a new application with storage reuse and check that the
    storage has been reused.
    """
    app_name = await get_app_name(ops_test)
    if storage_type(ops_test, app_name) == "rootfs":
        pytest.skip(
            "reuse of storage can only be used on deployments with persistent storage not on rootfs deployments"
        )

    writes_results = await stop_continous_writes(ops_test, app_name=app_name)

    time.sleep(70)  # Leave some time to write the oplog + lock (60s + a few more)
    unit_ids = [unit.name for unit in ops_test.model.applications[app_name].units]
    storage_ids = {}

    remaining_units = len(unit_ids)
    for unit_id in unit_ids:
        storage_ids[unit_id] = storage_id(ops_test, unit_id)
        await ops_test.model.applications[app_name].destroy_unit(unit_id)

        remaining_units -= 1
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=TIMEOUT,
            idle_period=20,
            wait_for_exact_units=remaining_units,
        )

    # Wait until all apps are cleaned up
    await ops_test.model.wait_for_idle(apps=[app_name], timeout=TIMEOUT, wait_for_exact_units=0)

    await ops_test.model.remove_application(
        app_name,
        block_until_done=True,
        destroy_storage=False,
    )

    await ops_test.model.deploy(
        database_charm,
        application_name=app_name,
        num_units=1,
        attach_storage=[tag.storage(storage_ids[unit_ids[0]])],
    )

    deployed_units = 1
    await ops_test.model.wait_for_idle(
        apps=[app_name],
        status="active",
        timeout=TIMEOUT,
        idle_period=60,
        wait_for_exact_units=deployed_units,
    )

    for unit_id in unit_ids[1:]:
        deployed_units += 1
        await ops_test.model.applications[app_name].add_unit(
            count=1, attach_storage=[tag.storage(storage_ids[unit_id])]
        )
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=TIMEOUT,
            idle_period=60,
            wait_for_exact_units=deployed_units,
        )

    await ops_test.model.wait_for_idle(
        apps=[app_name],
        status="active",
        timeout=TIMEOUT,
        idle_period=120,
        wait_for_exact_units=deployed_units,
    )

    assert len(ops_test.model.applications[app_name].units) == len(storage_ids)

    # check if previous volumes are attached to the units of the new cluster
    new_storage_ids = []
    for unit in ops_test.model.applications[app_name].units:
        new_storage_ids.append(storage_id(ops_test, unit.name))

    assert sorted(storage_ids.values()) == sorted(new_storage_ids), "Storage IDs mismatch"

    actual_writes = await count_writes(ops_test, app_name=app_name)
    assert writes_results["number"] == actual_writes


@pytest.mark.runner(["self-hosted", "linux", "X64", "jammy", "large"])
@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_storage_reuse_new_app_different_name(
    ops_test: OpsTest, database_charm, continuous_writes
):
    """Tests that we can reuse storage from a different cluster, with the same app name.

    For that, we completely remove the application while keeping the storages,
    and then we deploy a new application with storage reuse and check that the
    storage has been reused.
    """
    app_name = await get_app_name(ops_test)
    if storage_type(ops_test, app_name) == "rootfs":
        pytest.skip(
            "reuse of storage can only be used on deployments with persistent storage not on rootfs deployments"
        )

    writes_results = await stop_continous_writes(ops_test, app_name=app_name)
    time.sleep(70)  # Leave some time to write the oplog + lock (60s + a few more)
    unit_ids = [unit.name for unit in ops_test.model.applications[app_name].units]
    storage_ids = {}

    remaining_units = len(unit_ids)
    for unit_id in unit_ids:
        storage_ids[unit_id] = storage_id(ops_test, unit_id)
        await ops_test.model.applications[app_name].destroy_unit(unit_id)
        # Give some time to remove the unit. We don't use asyncio.sleep here to
        # leave time for each unit to be removed before removing the next one.
        # time.sleep(60)
        remaining_units -= 1
        await ops_test.model.wait_for_idle(
            apps=[app_name],
            status="active",
            timeout=TIMEOUT,
            idle_period=20,
            wait_for_exact_units=remaining_units,
        )

    # Wait until all apps are cleaned up
    await ops_test.model.wait_for_idle(apps=[app_name], timeout=TIMEOUT, wait_for_exact_units=0)

    await ops_test.model.remove_application(app_name, block_until_done=True, destroy_storage=False)

    new_app_name = OTHER_MONGODB_APP_NAME

    await ops_test.model.deploy(
        database_charm,
        application_name=new_app_name,
        num_units=1,
        attach_storage=[tag.storage(storage_ids[unit_ids[0]])],
    )
    deployed_units = 1
    await ops_test.model.wait_for_idle(
        apps=[new_app_name],
        status="active",
        timeout=TIMEOUT,
        idle_period=60,
        wait_for_exact_units=deployed_units,
    )

    for unit_id in unit_ids[1:]:
        deployed_units += 1
        await ops_test.model.applications[new_app_name].add_unit(
            count=1, attach_storage=[tag.storage(storage_ids[unit_id])]
        )
        await ops_test.model.wait_for_idle(
            apps=[new_app_name],
            status="active",
            timeout=TIMEOUT,
            idle_period=60,
            wait_for_exact_units=deployed_units,
        )

    assert len(ops_test.model.applications[new_app_name].units) == len(storage_ids)

    # check if previous volumes are attached to the units of the new cluster
    new_storage_ids = []
    for unit in ops_test.model.applications[new_app_name].units:
        new_storage_ids.append(storage_id(ops_test, unit.name))

    assert sorted(storage_ids.values()) == sorted(new_storage_ids), "Storage IDs mismatch"

    actual_writes = await count_writes(ops_test, app_name=new_app_name)
    assert writes_results["number"] == actual_writes
