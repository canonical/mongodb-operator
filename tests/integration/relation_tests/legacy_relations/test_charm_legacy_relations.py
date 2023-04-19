#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import subprocess
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from .helpers import (
    GRAYLOG_APP_NAME,
    ApiTimeoutError,
    _verify_rest_api_is_alive,
    auth_enabled,
    check_tls,
    get_application_relation_data,
    get_graylog_client,
)

DATABASE_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
DATABASE_APP_NAME = DATABASE_METADATA["name"]
ANOTHER_DATABASE_APP_NAME = "another-database"
PORT = 27017

NEW_RELATION_NAME = "first-database"
SECOND_NEW_RELATION_NAME = "second-database"
NEW_APP_PATH = "tests/integration/relation_tests/new_relations/application-charm"
NEW_APP_NAME = "application"

ELASTIC_APP_NAME = "elasticsearch"
APP_NAMES = [GRAYLOG_APP_NAME, ELASTIC_APP_NAME, DATABASE_APP_NAME]


@pytest.mark.abort_on_fail
async def test_build_deploy_charms(ops_test: OpsTest):
    """Deploy both charms (application and database) to use in the tests."""
    subprocess.check_output("juju set-model-constraints cores=2 mem=1G")
    # Deploy both charms (2 units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    db_charm = await ops_test.build_charm(".")

    await ops_test.model.deploy(GRAYLOG_APP_NAME, num_units=1)
    await ops_test.model.deploy(ELASTIC_APP_NAME, num_units=1, constraints="mem=4G")
    await ops_test.model.deploy(db_charm, num_units=2)

    # must be related before checking for active status (graylog will go into blocked without
    # necessary relations) we also choose not to raise on error since graylog and elasticsearch
    # can go into error before becoming idle/active  with necessary relations
    await ops_test.model.wait_for_idle(
        apps=[ELASTIC_APP_NAME, DATABASE_APP_NAME],
        raise_on_error=False,
        status="active",
        timeout=500,
    )
    await ops_test.model.wait_for_idle(
        apps=[GRAYLOG_APP_NAME], raise_on_error=False, status="blocked", timeout=2000
    )

    await ops_test.model.add_relation(GRAYLOG_APP_NAME, ELASTIC_APP_NAME)
    await ops_test.model.add_relation(GRAYLOG_APP_NAME, DATABASE_APP_NAME)

    await ops_test.model.wait_for_idle(
        apps=APP_NAMES, raise_on_error=False, status="active", timeout=2000
    )


async def test_relation_data(ops_test: OpsTest) -> None:
    """Test the relation data is set correctly for this legacy relation."""
    related_unit_name = ops_test.model.applications[DATABASE_APP_NAME].units[0].name

    hostname = await get_application_relation_data(
        ops_test, GRAYLOG_APP_NAME, "hostname", related_unit_name
    )
    port = await get_application_relation_data(
        ops_test, GRAYLOG_APP_NAME, "port", related_unit_name
    )
    rel_type = await get_application_relation_data(
        ops_test, GRAYLOG_APP_NAME, "type", related_unit_name
    )
    version = await get_application_relation_data(
        ops_test, GRAYLOG_APP_NAME, "version", related_unit_name
    )
    replset = await get_application_relation_data(
        ops_test, GRAYLOG_APP_NAME, "replset", related_unit_name
    )

    unit = ops_test.model.applications[DATABASE_APP_NAME].units[0]

    assert hostname == unit.public_address
    assert port == str(PORT)
    assert rel_type == "database"
    assert version == "5.0"
    assert replset == DATABASE_APP_NAME


async def test_mongodb_auth_disabled(ops_test: OpsTest) -> None:
    """Test mongodb no longer uses auth after relating to a legacy relation."""
    unit = ops_test.model.applications[DATABASE_APP_NAME].units[0]
    connection = unit.public_address + ":" + str(PORT)
    assert not await auth_enabled(
        connection
    ), "MongoDB requires authentication after legacy relation"


async def test_legacy_db_ops(ops_test: OpsTest) -> None:
    """Test graylog is able to do CRUD operations."""
    try:
        await _verify_rest_api_is_alive(ops_test)
    except ApiTimeoutError:
        assert False, "API is not available for graylog"

    g = await get_graylog_client(ops_test)

    # write data to graylog
    g.user_create("focal", "fossa", read_only=True)

    # read data from graylog
    user_info = g.user_get("focal")
    assert user_info["full_name"] == "focal", "unable to perform read/write operations"

    # update data in graylog
    g.user_permissions_set("focal", ["users:tokenlist"])
    user_info = g.user_get("focal")
    assert "users:tokenlist" in user_info["permissions"], "unable to perform update operations"

    # delete data from graylog
    g.user_permissions_clear("focal")
    user_info = g.user_get("focal")
    assert "users:tokenlist" not in user_info["permissions"], "unable to perform delete operations"


async def test_add_unit_joins_without_auth(ops_test: OpsTest):
    """Verify scaling mongodb with legacy relations supports no auth."""
    await ops_test.model.applications[DATABASE_APP_NAME].add_unit(count=1)
    await ops_test.model.wait_for_idle(
        apps=[DATABASE_APP_NAME], status="active", timeout=1000, wait_for_units=3
    )

    # verify auth is still disabled
    unit = ops_test.model.applications[DATABASE_APP_NAME].units[2]
    connection = unit.public_address + ":" + str(PORT)
    assert not await auth_enabled(
        connection
    ), "MongoDB requires disabled authentication to support legacy relations"


async def test_enable_tls(ops_test: OpsTest) -> None:
    """Verify each unit has TLS enabled after relating to the TLS application."""
    config = {"generate-self-signed-certificates": "true", "ca-common-name": "Test CA"}
    await ops_test.model.deploy("tls-certificates-operator", channel="edge", config=config)
    await ops_test.model.wait_for_idle(
        apps=["tls-certificates-operator"], status="active", timeout=1000
    )
    await ops_test.model.relate(DATABASE_APP_NAME, "tls-certificates-operator")

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[DATABASE_APP_NAME, "tls-certificates-operator"], status="active", timeout=1000
        )

    # Wait for all units enabling TLS.
    for unit in ops_test.model.applications[DATABASE_APP_NAME].units:
        assert await check_tls(ops_test, unit, enabled=True)

    # disable TLS by removing the relation.
    await ops_test.model.applications[DATABASE_APP_NAME].remove_relation(
        f"{DATABASE_APP_NAME}:certificates", "tls-certificates-operator:certificates"
    )
    await ops_test.model.wait_for_idle(apps=[DATABASE_APP_NAME], status="active", timeout=1000)


async def test_new_relation_fails_with_legacy(ops_test: OpsTest) -> None:
    """Verify new relation joining results in blocked when legacy relations exist.

    Legacy relations disable auth, therefore new relations should be prevented from joining
    """
    # app charm uses new relation interface
    app_charm = await ops_test.build_charm(NEW_APP_PATH)
    await ops_test.model.deploy(app_charm, num_units=1, application_name=NEW_APP_NAME)
    await ops_test.model.wait_for_idle(apps=[NEW_APP_NAME], status="active", timeout=1000)

    # a new relation to mongodb while its related to legacy relation should result in failure
    await ops_test.model.add_relation(f"{NEW_APP_NAME}:{NEW_RELATION_NAME}", DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle(apps=[DATABASE_APP_NAME], status="blocked", timeout=1000)

    assert (
        ops_test.model.applications[DATABASE_APP_NAME].units[0].workload_status == "blocked"
    ), "unit should go into blocked state when new relation and legacy relations are both added"

    # verify auth is still disabled
    unit = ops_test.model.applications[DATABASE_APP_NAME].units[0]
    connection = unit.public_address + ":" + str(PORT)
    assert not await auth_enabled(
        connection
    ), "MongoDB requires disabled authentication to support legacy relations"


async def test_legacy_relation_fails_with_new(ops_test: OpsTest) -> None:
    """Verify legacy relation joining results in blocked when new relations exist."""
    database = await ops_test.build_charm(".")
    await ops_test.model.deploy(database, num_units=1, application_name=ANOTHER_DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle(
        apps=[ANOTHER_DATABASE_APP_NAME], status="active", timeout=1000
    )

    # add new relation to pre-existing application from previous test
    await ops_test.model.add_relation(
        f"{NEW_APP_NAME}:{SECOND_NEW_RELATION_NAME}", ANOTHER_DATABASE_APP_NAME
    )
    await ops_test.model.wait_for_idle(
        apps=[NEW_APP_NAME, ANOTHER_DATABASE_APP_NAME], status="active", timeout=1000
    )

    # wait for new relation up to 5 minutes before adding legacy relation to prevent race
    # condition. TODO update when juju has a wait_for_relation function.
    try:
        for attempt in Retrying(stop=stop_after_delay(5 * 60), wait=wait_fixed(3)):
            with attempt:
                for rel in ops_test.model.relations:
                    endpoints = [endpoint.name for endpoint in rel.endpoints]
                    if "first-database" in endpoints and "database" in endpoints:
                        new_relation_joined = True
                        break

                if new_relation_joined:
                    break

    except RetryError:
        assert False, "New relation failed to join mongodb after 5 minutes."

    # add legacy relation
    await ops_test.model.add_relation(GRAYLOG_APP_NAME, ANOTHER_DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle(
        apps=[ANOTHER_DATABASE_APP_NAME], status="blocked", timeout=1000
    )

    assert (
        ops_test.model.applications[ANOTHER_DATABASE_APP_NAME].units[0].workload_status
        == "blocked"
    ), "unit should go into blocked state when new relation and legacy relations are both added"

    # verify auth is still enabled
    unit = ops_test.model.applications[ANOTHER_DATABASE_APP_NAME].units[0]
    connection = unit.public_address + ":" + str(PORT)
    assert await auth_enabled(
        connection, replset=ANOTHER_DATABASE_APP_NAME
    ), "MongoDB requires authentication to support new relations"
