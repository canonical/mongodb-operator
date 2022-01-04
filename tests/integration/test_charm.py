#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from tests.integration.helpers import pull_content_from_unit_file
from pymongo import MongoClient

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest) -> None:
    """Build and deploy one unit of MongoDB"""
    my_charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(my_charm)
    await ops_test.model.wait_for_idle()


@pytest.mark.abort_on_fail
async def test_status(ops_test: OpsTest) -> None:
    """Verifies that the application and unit are active"""
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=1000
    )
    assert len(ops_test.model.applications[APP_NAME].units) == 1
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
async def test_config_files_are_correct(ops_test: OpsTest) -> None:
    """Tests that mongo.conf as expected content"""
    # Get the expected contents from files.
    with open("tests/data/mongod.conf") as file:
        expected_mongodb_conf = file.read()

    # Pull the configuration files from each PostgreSQL instance.
    for unit in ops_test.model.applications[f"{APP_NAME}"].units:
        # Check that the remaining settings are as expected.
        unit_mongodb_conf_data = await pull_content_from_unit_file(
            unit, "/etc/mongod.conf"
        )
        expected_mongodb_conf = update_bind_ip(
            expected_mongodb_conf, unit.public_address
        )
        assert expected_mongodb_conf == unit_mongodb_conf_data


@pytest.mark.abort_on_fail
async def test_database_is_up_as_replica_set(ops_test: OpsTest) -> None:
    """Tests that mongodb is running as a replica set for the application units"""
    # construct URI for MongoDB replica set
    uri = "mongodb://"
    for i in range(0, len(ops_test.model.applications[APP_NAME].units)):
        if i:
            uri += ","
        unit = ops_test.model.applications[APP_NAME].units[i]
        uri += "{}:{}".format(unit.public_address, 27017)
    uri += "/?replicaSet=rs0"

    # connect to mongo replicaSet
    client = MongoClient(uri)

    # check mongo replicaset is ready
    assert client.server_info()

    # close connection
    client.close()


def update_bind_ip(conf: str, ip_address: str) -> str:
    """ Updates mongod.conf contents to use the given ip address for bindIp

    Args:
        conf: contents of mongod.conf
        ip_address: ip adress of unit
    """
    mongo_config = yaml.safe_load(conf)
    mongo_config["net"]["bindIp"] = "localhost,{}".format(ip_address)
    return yaml.dump(mongo_config)
