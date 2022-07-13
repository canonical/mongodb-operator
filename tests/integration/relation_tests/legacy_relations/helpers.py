#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from typing import Optional

import yaml
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from tests.integration.relation_tests.legacy_relations.api import GraylogApi

logger = logging.getLogger(__name__)
DEFAULT_REST_API_TIMEOUT = 120
GRAYLOG_PORT = 9000
GRAYLOG_APP_NAME = "graylog"


async def get_application_relation_data(
    ops_test: OpsTest, application_name: str, key: str, related_unit_name: str
) -> Optional[str]:
    """Get relation data for an application.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        key: key of data to be retrieved

    Returns:
        the that that was requested or None
            if no data in the relation

    Raises:
        ValueError if it's not possible to get application unit data.
    """
    related_app = related_unit_name.split("/")[0]
    unit_name = f"{application_name}/0"
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")

    data = yaml.safe_load(raw_data)
    logger.debug("data: %s", data)
    for relation in data[unit_name]["relation-info"]:
        if relation["endpoint"] == related_app:
            return relation["related-units"][related_unit_name]["data"][key]


async def get_graylog_client(ops_test: OpsTest):
    unit = ops_test.model.applications[GRAYLOG_APP_NAME].units[0]
    base_url = "http://{}:{}/api/".format(unit.public_address, GRAYLOG_PORT)
    return GraylogApi(
        base_url=base_url,
        username="admin",
        password=await get_password(ops_test, GRAYLOG_APP_NAME),
        token_name="graylog-charm",
    )


async def _verify_rest_api_is_alive(ops_test: OpsTest, timeout=DEFAULT_REST_API_TIMEOUT):
    try:
        for attempt in Retrying(stop=stop_after_delay(timeout), wait=wait_fixed(5)):
            with attempt:
                g = await get_graylog_client(ops_test)
                url = ""  # Will query using the base URL of the client, i.e. /api/
                resp = g.request(url)
                if not resp:
                    raise ApiTimeoutError()
    except RetryError:
        raise ApiTimeoutError()


async def get_password(ops_test: OpsTest, app_name: str) -> str:
    """Use the charm action to retrieve the password from provided unit.

    Returns:
        String with the password stored on the peer relation databag.
    """
    # can retrieve from any unit running unit so we pick the first
    unit_name = ops_test.model.applications[app_name].units[0].name
    unit_id = unit_name.split("/")[1]

    action = await ops_test.model.units.get(f"{app_name}/{unit_id}").run_action(
        "show-admin-password"
    )
    action = await action.wait()
    return action.results["admin-password"]


async def auth_enabled(connection: str, replset="mongodb") -> None:
    # try to access the database without password authentication

    client = MongoClient(connection, replicaset=replset)
    try:
        client.admin.command("replSetGetStatus")
    except OperationFailure as e:
        # error code 13 for OperationFailure is an authentication error, meaning we are not
        # authenticated to access the database. Thus auth is enabled.
        if e.code == 13:
            return True
        else:
            raise

    return False


class ApiTimeoutError(Exception):
    """Unable to access Graylog in a timely manner."""

    pass
