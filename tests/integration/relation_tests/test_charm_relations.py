#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest
from pymongo import MongoClient

from tests.integration.relation_tests.helpers import (
    get_application_relation_data,
)

logger = logging.getLogger(__name__)

APPLICATION_APP_NAME = "application"

DATABASE_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PORT = 27017
DATABASE_APP_NAME = DATABASE_METADATA["name"]
APP_NAMES = [APPLICATION_APP_NAME, DATABASE_APP_NAME]


@pytest.mark.abort_on_fail
async def test_deploy_charms(ops_test: OpsTest, application_charm, database_charm):
    """Deploy both charms (application and database) to use in the tests."""
    # Deploy both charms (2 units for each application to test that later they correctly
    # set data in the relation application databag using only the leader unit).
    await asyncio.gather(
        ops_test.model.deploy(
            application_charm,
            application_name=APPLICATION_APP_NAME,
            num_units=2,
        ),
        ops_test.model.deploy(
            database_charm,
            application_name=DATABASE_APP_NAME,
            num_units=2,
        ),
    )
    await ops_test.model.wait_for_idle(apps=APP_NAMES, status="active", wait_for_units=1)


@pytest.mark.abort_on_fail
async def test_database_relation_with_charm_libraries(ops_test: OpsTest):
    """Test basic functionality of database relation interface."""
    # Relate the charms and wait for them exchanging some connection data.
    await ops_test.model.add_relation(APPLICATION_APP_NAME, DATABASE_APP_NAME)
    await ops_test.model.wait_for_idle(apps=APP_NAMES, status="active")

    # TODO verify relation with database by writing/reading some data
    connection_string = await get_application_relation_data(ops_test, APPLICATION_APP_NAME, "uris")
    database = await get_application_relation_data(ops_test, APPLICATION_APP_NAME, "database")
    logger.info("%s", connection_string)
    client = MongoClient(
        connection_string,
        directConnection=False,
        connect=False,
        serverSelectionTimeoutMS=1000,
        connectTimeoutMS=2000,
    )
    # test crud operations
    db = client[database]
    test_collection = db['test_collection']
    ubuntu = {'release_name': 'Focal Fossa', 'version': 20.04, 'LTS': True}
    test_collection.insert(ubuntu)

    query = test_collection.find({}, {'release_name': 1})
    logger.error(query)
    assert query[0]['release_name'] == 'Focal Fossa'

    ubuntu_version = {'version': 20.04}
    ubuntu_name_updated = {'$set': {'release_name': 'Fancy Fossa'}}
    test_collection.update_one(ubuntu_version, ubuntu_name_updated)

    query = test_collection.find({}, {'release_name': 1})
    logger.error(query)
    assert query[0]['release_name'] == 'Fancy Fossa'

    test_collection.delete_one({'release_name': 'Fancy Fossa'})
    query = test_collection.find({}, {'release_name': 1})
    assert query.count() == 0

    client.close()
