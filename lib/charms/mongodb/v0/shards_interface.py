"""TODO: Add a proper docstring here.
"""
from ops.charm import CharmBase
from config import Config
from ops.framework import Object
import logging

from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    SecretNotFoundError,
    Unit,
    WaitingStatus,
)

logger = logging.getLogger(__name__)


# The unique Charmhub library identifier, never change it
LIBID = "55fee8fa73364fb0a2dc16a954b2fd4a"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

# TODO: add your code here! Happy coding!


class ShardingRequirer(Object):
    """TODO docstring - something about how this is used on config server side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.SHARDING_RELATIONS_NAME
    ) -> None:
        """Constructor for MongoDBProvider object.

        Args:
            relation_name: the name of the relation
        """
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_joined, self._on_relation_joined
        )
        # TODO Future PR, enable shard drainage by listening for relation departed events

    def _on_relation_joined(self, event):
        """TODO doc string"""
        if not self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info(
                "skipping relation joined event ShardingRequirer should only be executed by config-server"
            )
            return

        if not self.charm.unit.is_leader():
            return

        # todo verify it is related to a shard and not a replica

        # todo send out secrets


class ShardingProvider(Object):
    """TODO docstring - something about how this is used on shard side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.SHARDING_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object.

        Args:
            relation_name: the name of the relation
        """
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_joined, self._on_relation_joined
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )

        # TODO Future PR, enable shard drainage by listening for relation departed events

    def _on_relation_joined(self, event):
        """TODO doc string"""
        if not self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info(
                "skipping relation joined event ShardingProvider should only be executed by shards"
            )
            return

        if not self.charm.unit.is_leader():
            return

        # todo verify it is related to a config server and not a replica

    def _on_relation_changed(self, event):
        """TODO doc string"""
        if not self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info(
                "skipping relation changed event ShardingProvider should only be executed by shards"
            )
            return

        # TODO update all secrets and restart
