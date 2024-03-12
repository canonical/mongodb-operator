#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import pytest
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_attempt, wait_fixed

from ..tls_tests import helpers as tls_helpers

DIFFERENT_CERTS_APP_NAME = "self-signed-certificates-separate"
CERTS_APP_NAME = "self-signed-certificates"
SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
CONFIG_SERVER_APP_NAME = "config-server"
CLUSTER_COMPONENTS = [SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME, CONFIG_SERVER_APP_NAME]
SHARD_REL_NAME = "sharding"
CONFIG_SERVER_REL_NAME = "config-server"
CERT_REL_NAME = "certificates"
TIMEOUT = 10 * 60


# @pytest.mark.group(1)
# @pytest.mark.abort_on_fail
# async def test_build_and_deploy(ops_test: OpsTest) -> None:
#     """Build and deploy a sharded cluster."""
#     await deploy_cluster_components(ops_test)

#     # deploy the s3 integrator charm
#     await ops_test.model.deploy(CERTS_APP_NAME, channel="stable")

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[CERTS_APP_NAME, CONFIG_SERVER_APP_NAME, SHARD_ONE_APP_NAME, SHARD_TWO_APP_NAME],
            idle_period=20,
            raise_on_blocked=False,
            timeout=TIMEOUT,
            raise_on_error=False,
        )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=CLUSTER_COMPONENTS,
            idle_period=20,
            timeout=TIMEOUT,
            raise_on_blocked=False,
        )

@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_built_cluster_with_tls(ops_test: OpsTest) -> None:
    """Tests that the cluster can be integrated with TLS."""
    await integrate_cluster(ops_test)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=CLUSTER_COMPONENTS,
            idle_period=20,
            timeout=TIMEOUT,
        )

    await integrate_with_tls(ops_test)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=CLUSTER_COMPONENTS,
            idle_period=20,
            timeout=TIMEOUT,
        )

    await check_cluster_tls_enabled(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_disable_cluster_with_tls(ops_test: OpsTest) -> None:
    """Tests that the cluster can disable TLS."""
    await remove_tls_integrations(ops_test)
    await check_cluster_tls_disabled(ops_test)


@pytest.mark.group(1)
@pytest.mark.abort_on_fail
async def test_tls_then_build_cluster(ops_test: OpsTest) -> None:
    """Tests that the cluster can be integrated with TLS."""
    await destroy_cluster(ops_test)
    await deploy_cluster_components(ops_test)

    await integrate_with_tls(ops_test)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=CLUSTER_COMPONENTS,
            idle_period=20,
            timeout=TIMEOUT,
        )

    await integrate_cluster(ops_test)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=CLUSTER_COMPONENTS,
            idle_period=20,
            timeout=TIMEOUT,
        )

    await check_cluster_tls_enabled(ops_test)


# FUTURE PR - test inconsistencies in TLS settings across cluster


async def check_cluster_tls_disabled(ops_test: OpsTest) -> None:
    # check each replica set is running with TLS enabled
    for cluster_component in CLUSTER_COMPONENTS:
        for unit in ops_test.model.applications[cluster_component].units:
            await tls_helpers.check_tls(
                ops_test, unit, enabled=False, app_name=cluster_component, mongos=False
            )

    # check mongos is running with TLS enabled
    for unit in ops_test.model.applications[CONFIG_SERVER_APP_NAME].units:
        await tls_helpers.check_tls(
            ops_test, unit, enabled=False, app_name=CONFIG_SERVER_APP_NAME, mongos=True
        )


async def check_cluster_tls_enabled(ops_test: OpsTest) -> None:
    # check each replica set is running with TLS enabled
    for cluster_component in CLUSTER_COMPONENTS:
        for unit in ops_test.model.applications[cluster_component].units:
            await tls_helpers.check_tls(
                ops_test, unit, enabled=True, app_name=cluster_component, mongos=False
            )

    # check mongos is running with TLS enabled
    for unit in ops_test.model.applications[CONFIG_SERVER_APP_NAME].units:
        await tls_helpers.check_tls(
            ops_test, unit, enabled=True, app_name=CONFIG_SERVER_APP_NAME, mongos=True
        )


async def deploy_cluster_components(ops_test: OpsTest) -> None:
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(
        my_charm,
        num_units=2,
        config={"role": "config-server"},
        application_name=CONFIG_SERVER_APP_NAME,
    )
    await ops_test.model.deploy(
        my_charm, num_units=2, config={"role": "shard"}, application_name=SHARD_ONE_APP_NAME
    )
    await ops_test.model.deploy(
        my_charm, num_units=1, config={"role": "shard"}, application_name=SHARD_TWO_APP_NAME
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=CLUSTER_COMPONENTS,
            idle_period=20,
            timeout=TIMEOUT,
        )


async def destroy_cluster(ops_test):
    """Destroy cluster in a forceful way."""
    for app in CLUSTER_COMPONENTS:
        await ops_test.model.applications[app].destroy(force=True, no_wait=False)

    # destroy does not wait for applications to be removed, perform this check manually
    for attempt in Retrying(stop=stop_after_attempt(100), wait=wait_fixed(10), reraise=True):
        with attempt:
            # pytest_operator has a bug where the number of applications does not get correctly
            # updated. Wrapping the call with `fast_forward` resolves this
            async with ops_test.fast_forward():
                assert (
                    len(ops_test.model.applications) == 1
                ), "old cluster not destroyed successfully."


async def remove_tls_integrations(ops_test: OpsTest) -> None:
    """Removes the TLS integration from all cluster components."""
    for app in CLUSTER_COMPONENTS:
        await ops_test.model.applications[app].remove_relation(
            f"{app}:{CERT_REL_NAME}",
            f"{CERTS_APP_NAME}:{CERT_REL_NAME}",
        )


async def integrate_cluster(ops_test: OpsTest) -> None:
    """Integrates the cluster components with each other."""
    await ops_test.model.integrate(
        f"{SHARD_ONE_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )
    await ops_test.model.integrate(
        f"{SHARD_TWO_APP_NAME}:{SHARD_REL_NAME}",
        f"{CONFIG_SERVER_APP_NAME}:{CONFIG_SERVER_REL_NAME}",
    )


async def integrate_with_tls(ops_test: OpsTest) -> None:
    """Integrates cluster components with self-signed certs operator."""
    for app in CLUSTER_COMPONENTS:
        await ops_test.model.integrate(
            f"{CERTS_APP_NAME}:{CERT_REL_NAME}",
            f"{app}:{CERT_REL_NAME}",
        )
