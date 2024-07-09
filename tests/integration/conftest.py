#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import os
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest

from .sharding_tests import writes_helpers as writes_helpers


def ops_test(ops_test: OpsTest) -> OpsTest:
    if os.environ.get("CI") == "true":
        # Running in GitHub Actions; skip build step
        # (GitHub Actions uses a separate, cached build step. See .github/workflows/ci.yaml)
        packed_charms = json.loads(os.environ["CI_PACKED_CHARMS"])

        async def build_charm(charm_path, bases_index: int = None) -> Path:
            for charm in packed_charms:
                if Path(charm_path) == Path(charm["directory_path"]):
                    if bases_index is None or bases_index == charm["bases_index"]:
                        return charm["file_path"]
            raise ValueError(f"Unable to find .charm file for {bases_index=} at {charm_path=}")

        ops_test.build_charm = build_charm
    return ops_test


@pytest.fixture()
async def continuous_writes_to_shard_one(ops_test: OpsTest):
    """Adds writes to a shard named shard-one before test starts and clears writes at the end."""
    await writes_helpers.start_continous_writes_on_shard(
        ops_test,
        shard_name=writes_helpers.SHARD_ONE_APP_NAME,
        db_name=writes_helpers.SHARD_ONE_DB_NAME,
    )

    yield
    await writes_helpers.stop_continous_writes(
        ops_test,
        config_server_name=writes_helpers.CONFIG_SERVER_APP_NAME,
        db_name=writes_helpers.SHARD_ONE_DB_NAME,
    )
    await writes_helpers.remove_db_writes(ops_test, db_name=writes_helpers.SHARD_ONE_DB_NAME)


@pytest.fixture()
async def continuous_writes_to_shard_two(ops_test: OpsTest):
    """Adds writes to a shard named shard-one before test starts and clears writes at the end."""
    await writes_helpers.start_continous_writes_on_shard(
        ops_test,
        shard_name=writes_helpers.SHARD_TWO_APP_NAME,
        db_name=writes_helpers.SHARD_TWO_DB_NAME,
    )

    yield
    await writes_helpers.stop_continous_writes(
        ops_test,
        config_server_name=writes_helpers.CONFIG_SERVER_APP_NAME,
        db_name=writes_helpers.SHARD_TWO_DB_NAME,
    )
    await writes_helpers.remove_db_writes(ops_test, db_name=writes_helpers.SHARD_TWO_DB_NAME)
