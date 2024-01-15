# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock

import pytest


@pytest.fixture(autouse=True)
def ensure_secrets(mocker):
    mocker.patch(
        "charms.data_platform_libs.v0.data_interfaces.JujuVersion.has_secrets",
        new_callable=PropertyMock,
        return_value=True,
    )
