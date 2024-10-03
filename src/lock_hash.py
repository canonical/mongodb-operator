#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""A Data descriptor that is in charge of handling the filesystem lock hash value."""


import os
from logging import getLogger

import ops

from config import Config
from machine_helpers import ROOT_USER_GID

logger = getLogger(__name__)

HASH_KEY = "lockhash"
LOCK_PATH = Config.MONGODB_DATA_DIR / f".{HASH_KEY}"
UNDEFINED = "UNDEFINED"


class LockHashHandler:
    """Descriptor class for the lock hash stored in the file.

    In order to safely reuse storage, we need to be able to detect if we are reusing storage.
    This is done by maintaining two things: A file in the filesystem of the
    unit which stores a string, shared in the cluster, and the exact same
    string in the application secrets.
    If they have the same value, we're reusing storage in the same application/replicaset.
    If there's no file but a value in the secret, we're adding a new unit.
    If there's a file but no value in the secret, we're reusing in a new application context.
    """

    def __set__(self, obj: ops.CharmBase, value: str):
        """Sets the key in the dedicated file and in the storage."""
        logger.debug(f"Writing {value} in file for unit {obj.unit.name}")
        with open(LOCK_PATH, "w") as write_file:
            write_file.write(value)
        os.chmod(LOCK_PATH, 0o644)
        os.chown(LOCK_PATH, Config.SNAP_USER, ROOT_USER_GID)
        if obj.unit.is_leader():
            obj.set_secret(Config.Relations.APP_SCOPE, HASH_KEY, value)

    def __get__(self, *unused) -> str:
        """Optionally gets the key from the file."""
        try:
            return LOCK_PATH.read_text()
        except OSError as err:
            logger.info(f"Unable to read file because of {err}")
            return UNDEFINED
