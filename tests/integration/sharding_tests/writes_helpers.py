# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import subprocess
from pathlib import Path
from typing import Dict, List

import pytest
import yaml
from pymongo import MongoClient
from pytest_operator.plugin import OpsTest

from ..helpers import get_password
from .helpers import generate_mongodb_client

# TODO move these to a separate file for constants \ config
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
MONGOS_PORT = 27018
MONGOD_PORT = 27017
APP_NAME = "config-server"
APP_NAME_NEW = "config-server-new"

logger = logging.getLogger(__name__)

SHARD_ONE_APP_NAME = "shard-one"
SHARD_TWO_APP_NAME = "shard-two"
CONFIG_SERVER_APP_NAME = "config-server"

DEFAULT_DB_NAME = "new-db"
DEFAULT_COLL_NAME = "test_collection"
SHARD_ONE_DB_NAME = f"{SHARD_ONE_APP_NAME}-{DEFAULT_DB_NAME}".replace("-", "_")
SHARD_TWO_DB_NAME = f"{SHARD_TWO_APP_NAME}-{DEFAULT_DB_NAME}".replace("-", "_")


class ProcessError(Exception):
    """Raised when a process fails."""


class ProcessRunningError(Exception):
    """Raised when a process is running when it is not expected to be."""


async def mongos_uri(ops_test: OpsTest, config_server_name=APP_NAME) -> str:
    """Returns a uri for connecting to mongos."""
    password = await get_password(ops_test, app_name=config_server_name)
    hosts = [
        f"{unit.public_address}:{MONGOS_PORT}"
        for unit in ops_test.model.applications[config_server_name].units
    ]
    hosts = ",".join(hosts)
    return f"mongodb://operator:{password}@{hosts}/admin"


async def remove_db_writes(
    ops_test: OpsTest,
    db_name: str,
    coll_name: str = DEFAULT_COLL_NAME,
) -> bool:
    """Stop the DB process and remove any writes to the test collection."""
    # remove collection from database
    config_server_name = APP_NAME if APP_NAME in ops_test.model.applications else APP_NAME_NEW
    connection_string = await mongos_uri(ops_test, config_server_name)

    client = MongoClient(connection_string)
    db = client[db_name]

    # collection for continuous writes
    test_collection = db[coll_name]
    test_collection.drop()

    client.close()


@pytest.fixture()
async def continuous_writes_to_shard_one(ops_test: OpsTest):
    """Adds writes to a shard named shard-one before test starts and clears writes at the end."""
    await start_continous_writes_on_shard(
        ops_test,
        shard_name=SHARD_ONE_APP_NAME,
        db_name=SHARD_ONE_DB_NAME,
    )

    yield
    await stop_continous_writes(
        ops_test,
        config_server_name=CONFIG_SERVER_APP_NAME,
        db_name=SHARD_ONE_DB_NAME,
    )
    # await remove_db_writes(ops_test, db_name=SHARD_ONE_DB_NAME)


@pytest.fixture()
async def continuous_writes_to_shard_two(ops_test: OpsTest):
    """Adds writes to a shard named shard-one before test starts and clears writes at the end."""
    await start_continous_writes_on_shard(
        ops_test,
        shard_name=SHARD_TWO_APP_NAME,
        db_name=SHARD_TWO_DB_NAME,
    )

    yield
    await stop_continous_writes(
        ops_test,
        config_server_name=CONFIG_SERVER_APP_NAME,
        db_name=SHARD_TWO_DB_NAME,
    )
    # await remove_db_writes(ops_test, db_name=SHARD_TWO_DB_NAME)


async def start_continous_writes_on_shard(ops_test: OpsTest, shard_name: str, db_name: str):
    await start_continous_writes(
        ops_test,
        1,
        config_server_name=CONFIG_SERVER_APP_NAME,
        db_name=db_name,
        coll_name=DEFAULT_COLL_NAME,
    )
    # move continuous writes to shard-one
    mongos_client = await generate_mongodb_client(
        ops_test, app_name=CONFIG_SERVER_APP_NAME, mongos=True
    )

    mongos_client.admin.command("movePrimary", db_name, to=shard_name)


async def start_continous_writes(
    ops_test: OpsTest,
    starting_number: int,
    config_server_name=APP_NAME,
    db_name=DEFAULT_DB_NAME,
    coll_name=DEFAULT_COLL_NAME,
) -> None:
    """Starts continuous writes to MongoDB."""
    connection_string = await mongos_uri(ops_test, config_server_name)

    # run continuous writes in the background.
    subprocess.Popen(
        [
            "python3",
            "tests/integration/ha_tests/continuous_writes.py",
            connection_string,
            str(starting_number),
            db_name,
            coll_name,
        ]
    )


async def stop_continous_writes(
    ops_test: OpsTest,
    config_server_name=APP_NAME,
    db_name=DEFAULT_DB_NAME,
    collection_name=DEFAULT_COLL_NAME,
) -> int:
    """Stops continuous writes to MongoDB and returns the last written value."""
    # stop the process
    proc = subprocess.Popen(["pkill", "-9", "-f", db_name])

    # wait for process to be killed
    proc.communicate()

    connection_string = await mongos_uri(ops_test, config_server_name)

    client = MongoClient(connection_string)
    db = client[db_name]
    test_collection = db[collection_name]

    # last written value should be the highest number in the database.
    last_written_value = test_collection.find_one(sort=[("number", -1)])
    client.close()
    return last_written_value


async def count_shard_writes(
    ops_test: OpsTest,
    config_server_name=CONFIG_SERVER_APP_NAME,
    db_name="new-db",
    collection_name=DEFAULT_COLL_NAME,
) -> int:
    """New versions of pymongo no longer support the count operation, instead find is used."""
    connection_string = await mongos_uri(ops_test, config_server_name)

    client = MongoClient(connection_string)
    db = client[db_name]
    test_collection = db[collection_name]
    count = test_collection.count_documents({})
    client.close()
    return count


async def get_cluster_writes_count(
    ops_test,
    shard_app_names: List[str],
    db_names: List[str],
    config_server_name: str = CONFIG_SERVER_APP_NAME,
) -> Dict:
    """Returns a dictionary of the writes for each cluster_component and the total writes."""
    cluster_write_count = {}
    total_writes = 0
    for app_name in shard_app_names:
        cluster_write_count[app_name] = 0
        for db in db_names:
            component_writes = await count_shard_writes(ops_test, config_server_name, db_name=db)
            cluster_write_count[app_name] += component_writes
            total_writes += component_writes

    cluster_write_count["total_writes"] = total_writes
    return cluster_write_count


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
