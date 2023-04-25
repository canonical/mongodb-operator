#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import time

import ops
import pytest
import urllib3
from pytest_operator.plugin import OpsTest

from ..ha_tests import helpers as ha_helpers
from ..helpers import find_unit

MONGODB_EXPORTER_PORT = 9216
MEDIAN_REELECTION_TIME = 12


async def verify_endpoints(ops_test: OpsTest, unit: ops.model.Unit) -> str:
    """Verifies mongodb endpoint is functional on a given unit."""
    http = urllib3.PoolManager()

    unit_address = await ha_helpers.get_unit_ip(ops_test, unit.name)
    mongodb_exporter_url = f"http://{unit_address}:{MONGODB_EXPORTER_PORT}/metrics"
    mongo_resp = http.request("GET", mongodb_exporter_url)

    assert mongo_resp.status == 200

    # if configured correctly there should be more than one mongodb metric present
    mongodb_metrics = mongo_resp._body.decode("utf8")
    assert mongodb_metrics.count("mongo") > 1


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB."""
    if await ha_helpers.app_name(ops_test):
        return

    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=3)
    await ops_test.model.wait_for_idle()


async def test_endpoints(ops_test: OpsTest):
    """Sanity check that endpoints are running."""
    app = await ha_helpers.app_name(ops_test)
    application = ops_test.model.applications[app]

    for unit in application.units:
        await verify_endpoints(ops_test, unit)


async def test_endpoints_new_password(ops_test: OpsTest):
    """Verify that endpoints still function correctly after the monitor user password changes."""
    app = await ha_helpers.app_name(ops_test)
    application = ops_test.model.applications[app]
    leader_unit = await find_unit(ops_test, leader=True)
    action = await leader_unit.run_action("set-password", **{"username": "monitor"})
    action = await action.wait()
    # wait for non-leader units to receive relation changed event.
    time.sleep(3)
    await ops_test.model.wait_for_idle()
    for unit in application.units:
        await verify_endpoints(ops_test, unit)


async def test_endpoints_network_cut(ops_test: OpsTest):
    """Verify that endpoint still function correctly after a network cut."""
    app = await ha_helpers.app_name(ops_test)
    unit = ops_test.model.applications[app].units[0]
    hostname = await ha_helpers.unit_hostname(ops_test, unit.name)
    unit_ip = await ha_helpers.get_unit_ip(ops_test, unit.name)

    ha_helpers.cut_network_from_unit(hostname)
    # sleep for twice the median election time
    time.sleep(MEDIAN_REELECTION_TIME * 2)

    # wait until network is reestablished for the unit
    ha_helpers.restore_network_for_unit(hostname)
    ha_helpers.wait_network_restore(ops_test.model.info.name, hostname, unit_ip)
    await verify_endpoints(ops_test, unit)
