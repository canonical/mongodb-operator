#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
from pathlib import Path

import pytest
import yaml
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pytest_operator.plugin import OpsTest

from tests.integration.relation_tests.legacy_relations.helpers import (
    GRAYLOG_APP_NAME,
    ApiTimeoutError,
    _verify_rest_api_is_alive,
    get_application_relation_data,
    get_graylog_client,
)

DATABASE_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
DATABASE_APP_NAME = DATABASE_METADATA["name"]
PORT = 27017

ELASTIC_APP_NAME = "elasticsearch"
APP_NAMES = [GRAYLOG_APP_NAME, ELASTIC_APP_NAME, DATABASE_APP_NAME]


@pytest.mark.abort_on_fail
async def test_build_deploy_charms(ops_test: OpsTest):
    """Deploy both charms (application and database) to use in the tests."""
    # Deploy both charms (2 units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    db_charm = await ops_test.build_charm(".")

    await asyncio.gather(
        ops_test.model.deploy(
            GRAYLOG_APP_NAME,
            num_units=1,
        ),
        ops_test.model.deploy(ELASTIC_APP_NAME, num_units=1, constraints="mem=4G"),
        ops_test.model.deploy(
            db_charm,
            num_units=1,
        ),
    )

    # must be related before checking for active status (graylog will go into blocked without
    # necessary relations)
    await ops_test.model.add_relation(GRAYLOG_APP_NAME, ELASTIC_APP_NAME)
    await ops_test.model.add_relation(GRAYLOG_APP_NAME, DATABASE_APP_NAME)

    await ops_test.model.wait_for_idle(apps=APP_NAMES, status="active")


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
    # try to access the database without password authentication

    unit = ops_test.model.applications[DATABASE_APP_NAME].units[0]
    connection = unit.public_address + ":" + str(PORT)
    client = MongoClient(connection, replicaset="mongodb")
    try:
        client.admin.command("replSetGetStatus")
    except OperationFailure as e:
        # error code 13 for OperationFailure is an authentication error, meaning disabling of
        # authentication was unsuccessful
        if e.code == 13:
            assert False, "MongoDB requires authentication after legacy relation"
        else:
            raise


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
