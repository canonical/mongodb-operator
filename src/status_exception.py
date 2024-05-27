# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Exception with ops status"""

from ops import StatusBase


class StatusException(Exception):
    def __init__(self, status: StatusBase) -> None:
        super().__init__(status.message)
        self.status = status
