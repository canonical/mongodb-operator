#!/usr/bin/env python3
"""Code for handing statuses in the app and unit."""
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from ops.charm import CharmBase
from ops.framework import Object
from ops.model import StatusBase

from config import Config

# The unique Charmhub library identifier, never change it
LIBID = "9b0b9fac53244229aed5ffc5e62141eb"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


class MongoDBStatusHandler(Object):
    """Verifies versions across multiple integrated applications."""

    def __init__(
        self,
        charm: CharmBase,
    ) -> None:
        """Constructor for CrossAppVersionChecker.

        Args:
            charm: charm to inherit from.
        """
        super().__init__(charm, None)
        self.charm = charm

        # TODO Future PR: handle update_status

    # BEGIN Helpers

    def set_and_share_status(self, status: StatusBase):
        """Sets the charm status and shares to app status and config-server if applicable."""
        # TODO Future Feature/Epic: process other statuses, i.e. only set provided status if its
        # appropriate.
        self.charm.unit.status = status

        self.set_app_status()

        if self.charm.is_role(Config.Role.SHARD):
            self.share_status_to_config_server()

    def set_app_status(self):
        """TODO Future Feature/Epic: parse statuses and set a status for the entire app."""

    def are_all_units_ready_for_upgrade(self) -> bool:
        """Returns True if all charm units status's show that they are ready for upgrade."""
        goal_state = self.charm.model._backend._run(
            "goal-state", return_output=True, use_json=True
        )
        for _, unit_state in goal_state["units"].items():
            if unit_state["status"] == "active":
                continue
            if unit_state["status"] != "waiting":
                return False

            if not self.charm.get_cluster_mismatched_revision_status():
                return False

        return True

    def are_shards_status_ready_for_upgrade(self) -> bool:
        """Returns True if all integrated shards status's show that they are ready for upgrade.

        A shard is ready for upgrade if it is either in the waiting for upgrade status or active
        status.
        """
        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            return False

        for sharding_relation in self.charm.config_server.get_all_sharding_relations():
            for _, unit_data in sharding_relation.data.items():
                status_type = unit_data.get(Config.Status.STATUS_TYPE_KEY, None)
                status_messge = unit_data.get(Config.Status.STATUS_MESSAGE_KEY, None)
                if status_type is None:
                    return False
                if "ActiveStatus" in status_type:
                    continue
                if "WaitingStatus" not in status_type:
                    return False

                if (
                    status_messge
                    and status_messge != Config.Status.CONFIG_SERVER_WAITING_FOR_REFRESH.message
                ):
                    return False

        return True

    def share_status_to_config_server(self):
        """Shares this shards status info to the config server."""
        if not self.charm.is_role(Config.Role.SHARD):
            return

        if not (config_relation := self.charm.shard.get_config_server_relation()):
            return

        config_relation.data[self.charm.unit][Config.Status.STATUS_TYPE_KEY] = str(
            type(self.charm.unit.status)
        )

        config_relation.data[self.charm.unit][Config.Status.STATUS_MESSAGE_KEY] = str(
            self.charm.unit.status.message
        )

    # END: Helpers
