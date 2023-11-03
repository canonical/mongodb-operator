#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
async def legacy_charm(ops_test: OpsTest):
    """Build an application charm that uses the legacy interface.

    Note: this should only be used outside of the legacy integration tests, as those tests should
    test a real legacy application.
    """
    charm_path = "tests/integration/dummy_legacy_app"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def application_charm(ops_test: OpsTest):
    """Build the application charm."""
    charm_path = "tests/integration/relation_tests/new_relations/application-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def database_charm(ops_test: OpsTest):
    """Build the database charm."""
    charm = await ops_test.build_charm(".")
    return charm
