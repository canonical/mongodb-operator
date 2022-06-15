#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

# import shutil
import pytest
from pytest_operator.plugin import OpsTest


# @pytest.fixture(scope="module", autouse=True)
# def copy_provides_library_into_charm(ops_test: OpsTest):
#     """Copy the provides library to the database charm folder."""
#     library_path = "lib/charms/data_platform_libs/v0/database_provides.py"
#     install_path = "tests/integration/database-charm/" + library_path
#     shutil.copyfile(library_path, install_path)
#
#
# @pytest.fixture(scope="module", autouse=True)
# def copy_requires_library_into_charm(ops_test: OpsTest):
#     """Copy the requires library to the application charm folder."""
#     library_path = "lib/charms/data_platform_libs/v0/database_requires.py"
#     install_path = "tests/integration/application-charm/" + library_path
#     shutil.copyfile(library_path, install_path)


@pytest.fixture(scope="module")
async def application_charm(ops_test: OpsTest):
    """Build the application charm."""
    charm_path = "tests/integration/relation_tests/application-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def database_charm(ops_test: OpsTest):
    """Build the database charm."""
    charm = await ops_test.build_charm(".")
    return charm
