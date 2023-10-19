#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from pytest_operator.plugin import OpsTest
from urllib.parse import quote_plus
from ..helpers import get_password

MONGOS_PORT = 27018
MONGOD_PORT = 27017


async def generate_connection_string(ops_test: OpsTest, app_name: str, mongos: bool) -> str:
    """Returns a connection string for mongos/mongod to the provided application."""
    hosts = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    password = await get_password(ops_test, app_name)
    port = MONGOS_PORT if mongos else MONGOD_PORT
    hosts = [f"{host}:{port}" for host in hosts]
    hosts = ",".join(hosts)
    auth_source = ""
    database = "admin"

    return (
        f"mongodb://operator:"
        f"{quote_plus(password)}@"
        f"{hosts}/{quote_plus(database)}?"
        f"{auth_source}"
    )
