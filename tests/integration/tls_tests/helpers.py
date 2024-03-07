#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
from datetime import datetime

import ops
from charms.mongodb.v1.helpers import MONGO_SHELL
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_attempt, wait_exponential

from ..helpers import (
    get_app_name,
    get_application_relation_data,
    get_password,
    get_secret_content,
    get_secret_id,
)

# TODO move this to a separate constants file
PORT = 27017
MONGODB_SNAP_DATA_DIR = "/var/snap/charmed-mongodb/current"

MONGOD_CONF_DIR = f"{MONGODB_SNAP_DATA_DIR}/etc/mongod"
MONGO_COMMON_DIR = "/var/snap/charmed-mongodb/common"
EXTERNAL_CERT_PATH = f"{MONGOD_CONF_DIR}/external-ca.crt"
INTERNAL_CERT_PATH = f"{MONGOD_CONF_DIR}/internal-ca.crt"
EXTERNAL_PEM_PATH = f"{MONGOD_CONF_DIR}/external-cert.pem"

TLS_RELATION_NAME = "certificates"

logger = logging.getLogger(__name__)


class ProcessError(Exception):
    """Raised when a process fails."""


async def mongo_tls_command(ops_test: OpsTest, app_name=None, mongos=False) -> str:
    """Generates a command which verifies TLS status."""
    app_name = app_name or await get_app_name(ops_test)
    port = "27017" if not mongos else "27018"
    replica_set_hosts = [
        f"{unit.public_address}:{port}" for unit in ops_test.model.applications[app_name].units
    ]
    password = await get_password(ops_test, app_name=app_name)
    hosts = ",".join(replica_set_hosts)
    extra_args = f"?replicaSet={app_name}" if not mongos else ""
    replica_set_uri = f"mongodb://operator:{password}@{hosts}/admin{extra_args}"

    status_comand = "rs.status()" if not mongos else "sh.status()"
    return (
        f"{MONGO_SHELL} '{replica_set_uri}'  --eval '{status_comand}'"
        f" --tls --tlsCAFile {EXTERNAL_CERT_PATH}"
        f" --tlsCertificateKeyFile {EXTERNAL_PEM_PATH}"
    )


async def check_tls(
    ops_test: OpsTest, unit: ops.model.Unit, enabled: bool, app_name=None, mongos=False
) -> bool:
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
                mongod_tls_check = await mongo_tls_command(
                    ops_test, app_name=app_name, mongos=mongos
                )
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


async def time_file_created(ops_test: OpsTest, unit_name: str, path: str) -> int:
    """Returns the unix timestamp of when a file was created on a specified unit."""
    time_cmd = f"exec --unit {unit_name} --  ls -l --time-style=full-iso {path} "
    return_code, ls_output, _ = await ops_test.juju(*time_cmd.split())

    if return_code != 0:
        raise ProcessError(
            "Expected time command %s to succeed instead it failed: %s", time_cmd, return_code
        )

    return process_ls_time(ls_output)


async def time_process_started(ops_test: OpsTest, unit_name: str, process_name: str) -> int:
    """Retrieves the time that a given process started according to systemd."""
    time_cmd = f"exec --unit {unit_name} --  systemctl show {process_name} --property=ActiveEnterTimestamp"
    return_code, systemctl_output, _ = await ops_test.juju(*time_cmd.split())

    if return_code != 0:
        raise ProcessError(
            "Expected time command %s to succeed instead it failed: %s", time_cmd, return_code
        )

    return process_systemctl_time(systemctl_output)


def process_ls_time(ls_output):
    """Parse time representation as returned by the 'ls' command."""
    time_as_str = "T".join(ls_output.split("\n")[0].split(" ")[5:7])
    # further strip down additional milliseconds
    time_as_str = time_as_str[0:-3]
    d = datetime.strptime(time_as_str, "%Y-%m-%dT%H:%M:%S.%f")
    return d


def process_systemctl_time(systemctl_output):
    """Parse time representation as returned by the 'systemctl' command."""
    "ActiveEnterTimestamp=Thu 2022-09-22 10:00:00 UTC"
    time_as_str = "T".join(systemctl_output.split("=")[1].split(" ")[1:3])
    d = datetime.strptime(time_as_str, "%Y-%m-%dT%H:%M:%S")
    return d


async def scp_file_preserve_ctime(ops_test: OpsTest, unit_name: str, path: str) -> int:
    """Returns the unix timestamp of when a file was created on a specified unit."""
    # Retrieving the file
    filename = path.split("/")[-1]
    complete_command = f"scp --container mongod {unit_name}:{path} {filename}"
    return_code, scp_output, stderr = await ops_test.juju(*complete_command.split())

    if return_code != 0:
        logger.error(stderr)
        raise ProcessError(
            "Expected command %s to succeed instead it failed: %s; %s",
            complete_command,
            return_code,
            stderr,
        )

    return f"{filename}"


async def check_certs_correctly_distributed(
    ops_test: OpsTest, unit: ops.Unit, app_name=None
) -> None:
    """Comparing expected vs distributed certificates.

    Verifying certificates downloaded on the charm against the ones distributed by the TLS operator
    """
    app_name = app_name or await get_app_name(ops_test)
    app_secret_id = await get_secret_id(ops_test, app_name)
    unit_secret_id = await get_secret_id(ops_test, unit.name)
    app_secret_content = await get_secret_content(ops_test, app_secret_id)
    unit_secret_content = await get_secret_content(ops_test, unit_secret_id)
    app_current_crt = app_secret_content["csr-secret"]
    unit_current_crt = unit_secret_content["csr-secret"]

    # Get the values for certs from the relation, as provided by TLS Charm
    certificates_raw_data = await get_application_relation_data(
        ops_test, app_name, TLS_RELATION_NAME, "certificates"
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
