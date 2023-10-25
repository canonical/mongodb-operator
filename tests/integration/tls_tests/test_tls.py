#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import pytest
from ops import Unit
from pytest_operator.plugin import OpsTest

from ..helpers import get_application_relation_data, get_secret_content, get_secret_id
from .helpers import (
    EXTERNAL_CERT_PATH,
    INTERNAL_CERT_PATH,
    check_tls,
    scp_file_preserve_ctime,
    time_file_created,
    time_process_started,
)

MONGO_COMMON_DIR = "/var/snap/charmed-mongodb/common"
TLS_CERTIFICATES_APP_NAME = "tls-certificates-operator"
TLS_RELATION_NAME = "certificates"
DATABASE_APP_NAME = "mongodb"
TLS_TEST_DATA = "tests/integration/tls_tests/data"
DB_SERVICE = "snap.charmed-mongodb.mongod.service"


async def check_certs_correctly_distributed(ops_test: OpsTest, unit: Unit) -> None:
    """Comparing expected vs distributed certificates.

    Verifying certificates downloaded on the charm against the ones distributed by the TLS operator
    """
    app_secret_id = await get_secret_id(ops_test, DATABASE_APP_NAME)
    unit_secret_id = await get_secret_id(ops_test, unit.name)
    app_secret_content = await get_secret_content(ops_test, app_secret_id)
    unit_secret_content = await get_secret_content(ops_test, unit_secret_id)
    app_current_crt = app_secret_content["csr-secret"]
    unit_current_crt = unit_secret_content["csr-secret"]

    # Get the values for certs from the relation, as provided by TLS Charm
    certificates_raw_data = await get_application_relation_data(
        ops_test, DATABASE_APP_NAME, TLS_RELATION_NAME, "certificates"
    )
    certificates_data = json.loads(certificates_raw_data)

    external_item = [
        data
        for data in certificates_data
        if data["certificate_signing_request"].rstrip() == unit_current_crt.rstrip()
    ][0]
    internal_item = [
        data
        for data in certificates_data
        if data["certificate_signing_request"].rstrip() == app_current_crt.rstrip()
    ][0]

    # Get a local copy of the external cert
    external_copy_path = await scp_file_preserve_ctime(ops_test, unit.name, EXTERNAL_CERT_PATH)

    # Get the external cert value from the relation
    relation_external_cert = "\n".join(external_item["chain"])

    # CHECK: Compare if they are the same
    with open(external_copy_path) as f:
        external_contents_file = f.read()
        assert relation_external_cert == external_contents_file

    # Get a local copy of the internal cert
    internal_copy_path = await scp_file_preserve_ctime(ops_test, unit.name, INTERNAL_CERT_PATH)

    # Get the external cert value from the relation
    relation_internal_cert = "\n".join(internal_item["chain"])

    # CHECK: Compare if they are the same
    with open(internal_copy_path) as f:
        internal_contents_file = f.read()
        assert relation_internal_cert == internal_contents_file


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB and one unit of TLS."""
    async with ops_test.fast_forward():
        my_charm = await ops_test.build_charm(".")
        await ops_test.model.deploy(my_charm, num_units=3)
        await ops_test.model.wait_for_idle(apps=[DATABASE_APP_NAME], status="active")

        config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
        await ops_test.model.deploy(TLS_CERTIFICATES_APP_NAME, channel="stable", config=config)
        await ops_test.model.wait_for_idle(
            apps=[TLS_CERTIFICATES_APP_NAME], status="active", timeout=1000
        )


async def test_enable_tls(ops_test: OpsTest) -> None:
    """Verify each unit has TLS enabled after relating to the TLS application."""
    # Relate it to the PostgreSQL to enable TLS.
    await ops_test.model.relate(DATABASE_APP_NAME, TLS_CERTIFICATES_APP_NAME)

    await ops_test.model.wait_for_idle(status="active", timeout=1000, idle_period=60)

    # Wait for all units enabling TLS.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        assert await check_tls(ops_test, unit, enabled=True)


async def test_rotate_tls_key(ops_test: OpsTest) -> None:
    """Verify rotating tls private keys restarts mongod with new certificates.

    This test rotates tls private keys to randomly generated keys.
    """
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
        check_certs_correctly_distributed(ops_test, unit)

    # set external and internal key using auto-generated key for each unit
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        action = await unit.run_action(action_name="set-tls-private-key")
        action = await action.wait()
        assert action.status == "completed", "setting external and internal key failed."

    # wait for certificate to be available and processed. Can get receive two certificate
    # available events and restart twice so we want to ensure we are idle for at least 1 minute
    await ops_test.model.wait_for_idle(
        apps=[DATABASE_APP_NAME], status="active", timeout=1000, idle_period=60
    )

    # After updating both the external key and the internal key a new certificate request will be
    # made; then the certificates should be available and updated.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        new_external_cert_time = await time_file_created(ops_test, unit.name, EXTERNAL_CERT_PATH)
        new_internal_cert_time = await time_file_created(ops_test, unit.name, INTERNAL_CERT_PATH)
        new_mongod_service_time = await time_process_started(ops_test, unit.name, DB_SERVICE)

        check_certs_correctly_distributed(ops_test, unit)

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
        assert await check_tls(
            ops_test, unit, enabled=True
        ), f"tls is not enabled for {unit.name}."


async def test_set_tls_key(ops_test: OpsTest) -> None:
    """Verify rotating tls private keys restarts mongod with new certificates.

    This test rotates tls private keys to user specified keys.
    """
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

    with open(f"{TLS_TEST_DATA}/internal-key.pem") as f:
        internal_key_contents = f.readlines()
        internal_key_contents = "".join(internal_key_contents)

    # set external and internal key for each unit
    for unit_id in range(len(ops_test.model.applications[DATABASE_APP_NAME].units)):
        unit = ops_test.model.applications[DATABASE_APP_NAME].units[unit_id]

        with open(f"{TLS_TEST_DATA}/external-key-{unit_id}.pem") as f:
            external_key_contents = f.readlines()
            external_key_contents = "".join(external_key_contents)

        key_settings = {
            "internal-key": internal_key_contents,
            "external-key": external_key_contents,
        }

        action = await unit.run_action(
            action_name="set-tls-private-key",
            **key_settings,
        )
        action = await action.wait()
        assert action.status == "completed", "setting external and internal key failed."

    # wait for certificate to be available and processed. Can get receive two certificate
    # available events and restart twice so we want to ensure we are idle for at least 1 minute
    await ops_test.model.wait_for_idle(
        apps=[DATABASE_APP_NAME], status="active", timeout=1000, idle_period=60
    )

    # After updating both the external key and the internal key a new certificate request will be
    # made; then the certificates should be available and updated.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        new_external_cert_time = await time_file_created(ops_test, unit.name, EXTERNAL_CERT_PATH)
        new_internal_cert_time = await time_file_created(ops_test, unit.name, INTERNAL_CERT_PATH)
        new_mongod_service_time = await time_process_started(ops_test, unit.name, DB_SERVICE)

        check_certs_correctly_distributed(ops_test, unit)

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
        assert await check_tls(
            ops_test, unit, enabled=True
        ), f"tls is not enabled for {unit.name}."


async def test_disable_tls(ops_test: OpsTest) -> None:
    """Verify each unit has TLS disabled after removing relation to the TLS application."""
    # Remove the relation.
    await ops_test.model.applications[DATABASE_APP_NAME].remove_relation(
        f"{DATABASE_APP_NAME}:certificates", f"{TLS_CERTIFICATES_APP_NAME}:certificates"
    )

    await ops_test.model.wait_for_idle(
        apps=[DATABASE_APP_NAME], status="active", timeout=1000, idle_period=60
    )

    # Wait for all units disabling TLS.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        assert await check_tls(ops_test, unit, enabled=False)
