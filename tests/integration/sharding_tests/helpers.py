#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from typing import List, Optional
from urllib.parse import quote_plus

from pymongo import MongoClient
from pytest_operator.plugin import OpsTest

from ..helpers import get_password

MONGOS_PORT = 27018
MONGOD_PORT = 27017


async def generate_mongodb_client(ops_test: OpsTest, app_name: str, mongos: bool):
    """Returns a MongoDB client for mongos/mongod."""
    hosts = [unit.public_address for unit in ops_test.model.applications[app_name].units]
    password = await get_password(ops_test, app_name)
    port = MONGOS_PORT if mongos else MONGOD_PORT
    hosts = [f"{host}:{port}" for host in hosts]
    hosts = ",".join(hosts)
    auth_source = ""
    database = "admin"

    return MongoClient(
        f"mongodb://operator:"
        f"{quote_plus(password)}@"
        f"{hosts}/{quote_plus(database)}?"
        f"{auth_source}"
    )


def write_data_to_mongodb(client, db_name, coll_name, content) -> None:
    """Writes data to the provided collection and database."""
    db = client[db_name]
    horses_collection = db[coll_name]
    horses_collection.insert_one(content)


def verify_data_mongodb(client, db_name, coll_name, key, value) -> bool:
    """Checks a key/value pair for a provided collection and database."""
    db = client[db_name]
    test_collection = db[coll_name]
    query = test_collection.find({}, {key: 1})
    return query[0][key] == value


def get_cluster_shards(mongos_client) -> set:
    """Returns a set of the shard members."""
    shard_list = mongos_client.admin.command("listShards")
    curr_members = [member["_id"] for member in shard_list["shards"]]
    return set(curr_members)


def get_databases_for_shard(mongos_client, shard_name) -> Optional[List[str]]:
    config_db = mongos_client["config"]
    if "databases" not in config_db.list_collection_names():
        return None

    databases_collection = config_db["databases"]

    if databases_collection is None:
        return

    return databases_collection.distinct("_id", {"primary": shard_name})
