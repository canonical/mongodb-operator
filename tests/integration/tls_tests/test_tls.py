#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from time import sleep

import pytest
from pytest_operator.plugin import OpsTest

from tests.integration.helpers import find_unit
from tests.integration.tls_tests.helpers import (
    check_tls,
    time_file_created,
    time_process_started,
)

TLS_CERTIFICATES_APP_NAME = "tls-certificates-operator"
DATABASE_APP_NAME = "mongodb"
PRIVATE_KEY_PATH = "tests/integration/tls_tests/data/key.txt"
EXTERNAL_CERT_PATH = "/etc/mongodb/external-ca.crt"
INTERNAL_CERT_PATH = "/etc/mongodb/internal-ca.crt"
DB_SERVICE = "mongod.service"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB and one unit of TLS."""
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm, num_units=2)
    await ops_test.model.wait_for_idle()

    config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
    await ops_test.model.deploy(TLS_CERTIFICATES_APP_NAME, channel="edge", config=config)
    await ops_test.model.wait_for_idle(
        apps=[TLS_CERTIFICATES_APP_NAME], status="active", timeout=1000
    )


async def test_enable_tls(ops_test: OpsTest) -> None:
    """Verify each unit has TLS enabled after relating to the TLS application."""
    # Relate it to the PostgreSQL to enable TLS.
    await ops_test.model.relate(DATABASE_APP_NAME, TLS_CERTIFICATES_APP_NAME)
    await ops_test.model.wait_for_idle(status="active", timeout=1000)

    # Wait for all units enabling TLS.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        assert await check_tls(ops_test, unit, enabled=True)


async def test_set_tls_key(ops_test: OpsTest) -> None:
    """Verify rotating tls private keys restarts mongod with new certificates."""
    # dict of values for cert file certion and mongod service start times. After resetting the
    # private keys these certificates should be updated and the mongod service should be
    # restarted
    original_tls_times = {}
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        original_tls_times[unit.name] = {}
        original_tls_times[unit.name]["external_cert"] = await time_file_created(
            ops_test, unit.name, EXTERNAL_CERT_PATH
        )
        original_tls_times[unit.name]["internal_cert"] = await time_file_created(
            ops_test, unit.name, INTERNAL_CERT_PATH
        )
        original_tls_times[unit.name]["mongod_service"] = await time_process_started(
            ops_test, unit.name, DB_SERVICE
        )

    with open(PRIVATE_KEY_PATH) as f:
        key_contents = f.readlines()
        key_contents = "".join(key_contents)

    # set internal key
    leader_unit = await find_unit(ops_test, leader=True)
    leader_unit = await find_unit(ops_test, leader=True)
    await leader_unit.run_action(
        action_name="set-tls-private-key", params="=".join(["external-key", key_contents])
    )

    # set external key
    leader_unit = await find_unit(ops_test, leader=True)
    await leader_unit.run_action(
        action_name="set-tls-private-key", params="=".join(["internal-key", key_contents])
    )

    # sleep for long enough to process new certificate request and update certs
    sleep(30)

    # After updating both the external key and the internal key a new certificate request will be
    # made; then the certificates should be available and updated.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        new_external_cert_time = await time_file_created(ops_test, unit.name, EXTERNAL_CERT_PATH)
        new_internal_cert_time = await time_file_created(ops_test, unit.name, INTERNAL_CERT_PATH)
        new_mongod_service_time = await time_process_started(ops_test, unit.name, DB_SERVICE)

        assert (
            new_external_cert_time > original_tls_times[unit.name]["external_cert"]
        ), f"external cert for {unit.name} was not updated."
        assert (
            new_internal_cert_time > original_tls_times[unit.name]["internal_cert"]
        ), f"internal cert for {unit.name} was not updated."

        # Once the certificate requests are processed and updated the mongod.service should be
        # restarted
        assert (
            new_mongod_service_time > original_tls_times[unit.name]["mongod_service"]
        ), f"mongod service for {unit.name} was not restarted."

    # Verify that TLS is functioning on all units.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        assert await check_tls(ops_test, unit, enabled=True)


async def test_disable_tls(ops_test: OpsTest) -> None:
    """Verify each unit has TLS disabled after removing relation to the TLS application."""
    # Remove the relation.
    await ops_test.model.applications[DATABASE_APP_NAME].remove_relation(
        f"{DATABASE_APP_NAME}:certificates", f"{TLS_CERTIFICATES_APP_NAME}:certificates"
    )
    await ops_test.model.wait_for_idle(apps=[DATABASE_APP_NAME], status="active", timeout=1000)

    # Wait for all units disabling TLS.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        assert await check_tls(ops_test, unit, enabled=False)
