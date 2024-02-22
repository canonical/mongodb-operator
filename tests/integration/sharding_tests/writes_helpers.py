# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
from pathlib import Path

import yaml
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest

from ..helpers import get_password

# TODO move these to a separate file for constants \ config
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MONGOS_PORT = 27018
APP_NAME = "config-server-one"  # todo change this back to config-server

logger = logging.getLogger(__name__)


class ProcessError(Exception):
    """Raised when a process fails."""


class ProcessRunningError(Exception):
    """Raised when a process is running when it is not expected to be."""


async def mongos_uri(ops_test: OpsTest, config_server_name=APP_NAME) -> str:
    password = await get_password(ops_test, app_name=config_server_name)
    hosts = [
        f"{unit.public_address}:{MONGOS_PORT}"
        for unit in ops_test.model.applications[config_server_name].units
    ]
    hosts = ",".join(hosts)
    return f"mongodb://operator:{password}@{hosts}/admin"


async def clear_db_writes(ops_test: OpsTest, config_server_name=APP_NAME) -> bool:
    """Stop the DB process and remove any writes to the test collection."""
    await stop_continous_writes(ops_test)

    # remove collection from database
    connection_string = await mongos_uri(ops_test, config_server_name)

    client = MongoClient(connection_string)
    db = client["new-db"]

    # collection for continuous writes
    test_collection = db["test_collection"]
    test_collection.drop()

    client.close()


async def start_continous_writes(
    ops_test: OpsTest, starting_number: int, config_server_name=APP_NAME
) -> None:
    """Starts continuous writes to MongoDB with available replicas.

    In the future this should be put in a dummy charm.
    """
    connection_string = await mongos_uri(ops_test, config_server_name)

    # run continuous writes in the background.
    subprocess.Popen(
        [
            "python3",
            "tests/integration/ha_tests/continuous_writes.py",
            connection_string,
            str(starting_number),
        ]
    )


async def stop_continous_writes(ops_test: OpsTest, config_server_name=APP_NAME) -> int:
    """Stops continuous writes to MongoDB and returns the last written value.

    In the future this should be put in a dummy charm.
    """
    # stop the process
    proc = subprocess.Popen(["pkill", "-9", "-f", "continuous_writes.py"])

    # wait for process to be killed
    proc.communicate()

    connection_string = await mongos_uri(ops_test, config_server_name)

    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]

    # last written value should be the highest number in the database.
    last_written_value = test_collection.find_one(sort=[("number", -1)])
    client.close()
    return last_written_value


async def count_writes(ops_test: OpsTest, config_server_name=APP_NAME) -> int:
    """New versions of pymongo no longer support the count operation, instead find is used."""
    connection_string = await mongos_uri(ops_test, config_server_name)
    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]
    # TODO shard collection
    # TODO return count on each shard
    count = test_collection.count_documents({})
    client.close()
    return count


async def verify_writes(ops_test: OpsTest, config_server_name=APP_NAME):
    # verify that no writes to the db were missed
    total_expected_writes = await stop_continous_writes(ops_test)
    actual_writes = await count_writes(ops_test, config_server_name)

    # todo rework this whole function
    assert total_expected_writes["number"] == actual_writes, "writes to the db were missed."


async def insert_unwanted_data(ops_test: OpsTest, config_server_name=APP_NAME) -> None:
    """Inserts the data into the MongoDB cluster via primary replica."""
    connection_string = await mongos_uri(ops_test, config_server_name)

    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]
    test_collection.insert_one({"unwanted_data": "bad data 1"})
    test_collection.insert_one({"unwanted_data": "bad data 2"})
    test_collection.insert_one({"unwanted_data": "bad data 3"})
    client.close()
