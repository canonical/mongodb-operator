# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Class for exception with ops status."""

from ops import StatusBase


class StatusException(Exception):
    """Exception with ops status."""

    def __init__(self, status: StatusBase) -> None:
        super().__init__(status.message)
        self.status = status
