#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from typing import Optional

import ops
import yaml
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    Retrying,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    wait_fixed,
)

from .api import GraylogApi

logger = logging.getLogger(__name__)
DEFAULT_REST_API_TIMEOUT = 120
GRAYLOG_PORT = 9000
GRAYLOG_APP_NAME = "graylog"

MONGODB_SNAP_DATA_DIR = "/var/snap/charmed-mongodb/current"

MONGOD_CONF_DIR = f"{MONGODB_SNAP_DATA_DIR}/etc/mongod"
MONGO_COMMON_DIR = "/var/snap/charmed-mongodb/common"
EXTERNAL_CERT_PATH = f"{MONGOD_CONF_DIR}/external-ca.crt"
INTERNAL_CERT_PATH = f"{MONGOD_CONF_DIR}/internal-ca.crt"
EXTERNAL_PEM_PATH = f"{MONGOD_CONF_DIR}/external-cert.pem"


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


async def mongo_tls_command(ops_test: OpsTest) -> str:
    """Generates a command which verifies TLS status."""
    app = "mongodb"
    replica_set_hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(replica_set_hosts)
    replica_set_uri = f"mongodb://{hosts}/admin?replicaSet={app}"

    return (
        f"charmed-mongodb.mongosh '{replica_set_uri}'  --eval 'rs.status()'"
        f" --tls --tlsCAFile {EXTERNAL_CERT_PATH}"
        f" --tlsCertificateKeyFile {EXTERNAL_PEM_PATH}"
    )


async def check_tls(ops_test: OpsTest, unit: ops.model.Unit, enabled: bool) -> bool:
    """Returns whether TLS is enabled on the specific PostgreSQL instance.

    Args:
        ops_test: The ops test framework instance.
        unit: The unit to be checked.
        enabled: check if TLS is enabled/disabled

    Returns:
        Whether TLS is enabled/disabled.
    """
    try:
        for attempt in Retrying(
            stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=30)
        ):
            with attempt:
                mongod_tls_check = await mongo_tls_command(ops_test)
                check_tls_cmd = f"exec --unit {unit.name} -- {mongod_tls_check}"
                return_code, _, _ = await ops_test.juju(*check_tls_cmd.split())
                tls_enabled = return_code == 0
                if enabled != tls_enabled:
                    raise ValueError(
                        f"TLS is{' not' if not tls_enabled else ''} enabled on {unit.name}"
                    )
                return True
    except RetryError:
        return False
