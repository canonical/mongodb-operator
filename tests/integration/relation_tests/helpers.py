#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from typing import Optional

import yaml
from pytest_operator.plugin import OpsTest


async def build_connection_string(ops_test: OpsTest, application_name: str) -> str:
    """Build a PostgreSQL connection string.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application

    Returns:
        a PostgreSQL connection string
    """
    # Get the connection data exposed to the application through the relation.
    database = f'data_platform_{application_name.replace("-", "_")}'
    username = await get_application_relation_data(ops_test, application_name, "username")
    password = await get_application_relation_data(ops_test, application_name, "password")
    endpoints = await get_application_relation_data(ops_test, application_name, "endpoints")
    host = endpoints.split(",")[0].split(":")[0]

    # Build the complete connection string to connect to the database.
    # TODO update this to be the MongoDB connection string
    return f"dbname='{database}' user='{username}' host='{host}' password='{password}' connect_timeout=10"


async def get_application_relation_data(
    ops_test: OpsTest, application_name: str, key: str
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
    unit_name = f"{application_name}/0"
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)
    return data[unit_name]["relation-info"][0]["application-data"].get(key)
