#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from typing import Optional

import yaml
from pytest_operator.plugin import OpsTest
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed


async def get_application_relation_data(
    ops_test: OpsTest,
    application_name: str,
    relation_name: str,
    key: str,
    relation_id: str = None,
    relation_alias: str = None,
) -> Optional[str]:
    """Get relation data for an application.

    Args:
        ops_test: The ops test framework instance
        application_name: The name of the application
        relation_name: name of the relation to get connection data from
        key: key of data to be retrieved
        relation_id: id of the relation to get connection data from
        relation_alias: alias of the relation (like a connection name)
            to get connection data from
    Returns:
        the that that was requested or None
            if no data in the relation
    Raises:
        ValueError if it's not possible to get application unit data
            or if there is no data for the particular relation endpoint
            and/or alias.
    """
    unit_name = f"{application_name}/0"
    raw_data = (await ops_test.juju("show-unit", unit_name))[1]

    if not raw_data:
        raise ValueError(f"no unit info could be grabbed for {unit_name}")
    data = yaml.safe_load(raw_data)

    # Filter the data based on the relation name.
    relation_data = [v for v in data[unit_name]["relation-info"] if v["endpoint"] == relation_name]

    if relation_id:
        # Filter the data based on the relation id.
        relation_data = [v for v in relation_data if v["relation-id"] == relation_id]

    if relation_alias:
        import pdb

        pdb.set_trace()
        # Filter the data based on the cluster/relation alias.
        relation_data = [
            v
            for v in relation_data
            if json.loads(v["application-data"]["data"])["alias"] == relation_alias
        ]

    if len(relation_data) == 0:
        raise ValueError(
            f"no relation data could be grabbed on relation with endpoint {relation_name} and alias {relation_alias}"
        )

    return relation_data[0]["application-data"].get(key)


async def verify_application_data(
    ops_test: OpsTest,
    application_name: str,
    database_app: str,
    relation_name: str,
) -> bool:
    """Verifies the application relation metadata matches with the MongoDB deployment.

    Specifically, it verifies that all units are present in the URI and that there are no
    additional units
    """
    try:
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
            with attempt:
                endpoints_str = await get_application_relation_data(
                    ops_test, application_name, relation_name, "endpoints"
                )
                for unit in ops_test.model.applications[database_app].units:
                    if unit.public_address not in endpoints_str:
                        raise Exception(f"unit {unit.name} not present in connection URI")

                if len(endpoints_str.split(",")) != len(
                    ops_test.model.applications[database_app].units
                ):
                    raise Exception(
                        "number of endpoints in replicaset URI do not match number of units"
                    )

    except RetryError:
        return False

    return True


async def get_secret_data(ops_test, secret_uri):
    secret_unique_id = secret_uri.split("/")[-1]
    complete_command = f"show-secret {secret_uri} --reveal --format=json"
    _, stdout, _ = await ops_test.juju(*complete_command.split())
    return json.loads(stdout)[secret_unique_id]["content"]["Data"]


async def get_connection_string(
    ops_test: OpsTest, app_name, relation_name, relation_id=None, relation_alias=None
) -> str:
    secret_uri = await get_application_relation_data(
        ops_test, app_name, relation_name, "secret-user", relation_id, relation_alias
    )

    first_relation_user_data = await get_secret_data(ops_test, secret_uri)
    return first_relation_user_data.get("uris")
