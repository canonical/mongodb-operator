#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from typing import Optional
from urllib.parse import quote_plus

import yaml
from pytest_operator.plugin import OpsTest

import logging
logger = logging.getLogger(__name__)


async def get_application_relation_data(
    ops_test: OpsTest, application_name: str, key: str
) -> Optional[str]:
    """Get relation data for an application.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        key: key of data to be retrieved

    Returns:
        the that that was requested or None
            if no data in the relation

    Raises:
        ValueError if it's not possible to get application unit data.
    """
    unit_name = f"{application_name}/0"
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]
    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)
    return data[unit_name]["relation-info"][0]["application-data"].get(key)
