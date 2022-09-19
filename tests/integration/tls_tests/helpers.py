#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import ops
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_attempt, wait_exponential
from tests.integration.ha_tests.helpers import app_name
from tests.integration.helpers import get_password

PORT = 27017


async def mongo_tls_command(ops_test: OpsTest) -> str:
    """Generates a command which verifies TLS status."""
    app = await app_name(ops_test)
    replica_set_hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    password = await get_password(ops_test, app)
    hosts = ["{}:{}".format(replica_ip, PORT) for replica_ip in replica_set_hosts]
    hosts = ",".join(hosts)
    replica_set_uri = f"mongodb://admin:" f"{password}@" f"{hosts}/admin?replicaSet={app}"

    return (
        f"mongo '{replica_set_uri}'  --eval 'rs.status()'"
        f" --tls --tlsCAFile /etc/mongodb/external-ca.crt"
        f" --tlsCertificateKeyFile /etc/mongodb/external-cert.pem"
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
                check_tls_cmd = f"run --unit {unit.name} -- {mongod_tls_check}"
                return_code, a, b = await ops_test.juju(*check_tls_cmd.split())
                tls_enabled = return_code == 0
                if enabled != tls_enabled:
                    raise ValueError(
                        f"TLS is{' not' if not tls_enabled else ''} enabled on {unit.name}"
                    )
                return True
    except RetryError:
        return False
