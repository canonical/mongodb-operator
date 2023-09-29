# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage relations between config-servers and shards.

This class handles the sharing of secrets between sharded components, adding shards, and removing
shards.
"""
import json
import logging
import time
from typing import Optional, Set

from charms.mongodb.v0.helpers import KEY_FILE
from charms.mongodb.v0.mongodb import (
    MongoDBConnection,
    NotReadyError,
    OperationFailure,
    PyMongoError,
)
from charms.mongodb.v0.mongos import (
    MongosConnection,
    ShardNotInClusterError,
    ShardNotPlannedForRemovalError,
)
from charms.mongodb.v0.users import MongoDBUser, OperatorUser
from ops.charm import CharmBase, RelationDepartedEvent
from ops.framework import Object
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

from config import Config

logger = logging.getLogger(__name__)


# The unique Charmhub library identifier, never change it
LIBID = "55fee8fa73364fb0a2dc16a954b2fd4a"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1
KEYFILE_KEY = "key-file"
OPERATOR_PASSWORD_KEY = "operator-password"
HOSTS_KEY = "host"


class RemoveLastShardError(Exception):
    """Raised when there is an attempt to remove the last shard in the cluster."""


class ShardingProvider(Object):
    """Manage relations between the config server and the shard, on the config-server's side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.CONFIG_SERVER_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingRequirer object."""
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_joined, self._on_relation_joined
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_event
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_departed, self._on_relation_event
        )

        # TODO Follow up PR, handle rotating passwords

    def _on_relation_joined(self, event):
        """Handles providing shards with secrets and adding shards to the config server."""
        if self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info(
                "skipping relation joined event ShardingRequirer is only be executed by config-server"
            )
            return

        if not self.charm.unit.is_leader():
            return

        if not self.charm.db_initialised:
            event.defer()

        # TODO Future PR, sync tls secrets and PBM password
        self._update_relation_data(
            event.relation.id,
            {
                OPERATOR_PASSWORD_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE,
                    MongoDBUser.get_password_key_name_for_user("operator"),
                ),
                KEYFILE_KEY: self.charm.get_secret(
                    Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME
                ),
                HOSTS_KEY: json.dumps(self.charm._unit_ips),
            },
        )

    def _on_relation_event(self, event):
        """Handles adding, removing, and updating of shards."""
        if self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.CONFIG_SERVER):
            logger.info(
                "skipping relation joined event ShardingRequirer is only be executed by config-server"
            )
            return

        if not self.charm.unit.is_leader():
            return

        if not self.charm.db_initialised:
            event.defer()

        departed_relation_id = None
        if type(event) is RelationDepartedEvent:
            departed_relation_id = event.relation.id

        try:
            logger.info("Adding shards not present in cluster.")
            self.add_shards(departed_relation_id)
            self.remove_shards(departed_relation_id)
            # TODO Future PR, enable updating shards by listening for relation changed events
            # TODO Future PR, enable shard drainage by listening for relation departed events
        except OperationFailure as e:
            if e.code == 20:
                logger.error(
                    "Cannot not remove the last shard from cluster, this is forbidden by mongos."
                )
                # we should not lose connection with the shard, prevent other hooks from executing.
                raise RemoveLastShardError()
        except (PyMongoError, NotReadyError) as e:
            logger.error("Deferring _on_relation_event for shards interface since: error=%r", e)
            event.defer()
            return

    def add_shards(self, departed_shard_id):
        """Adds shards to cluster.

        raises: PyMongoError
        """
        with MongosConnection(self.charm.mongos_config) as mongo:
            cluster_shards = mongo.get_shard_members()
            relation_shards = self._get_shards_from_relations(departed_shard_id)

            # TODO Future PR, limit number of shards add at a time, based on the number of
            # replicas in the primary shard
            for shard in relation_shards - cluster_shards:
                shard_hosts = self._get_shard_hosts(shard)
                if not len(shard_hosts):
                    logger.info("host info for shard %s not yet added, skipping", shard)
                    continue

                logger.info("Adding shard: %s ", shard)
                mongo.add_shard(shard, shard_hosts)

    def remove_shards(self, departed_shard_id):
        """Removes shards from cluster.

        raises: PyMongoError, NotReadyError
        """
        with MongosConnection(self.charm.mongos_config) as mongo:
            cluster_shards = mongo.get_shard_members()
            relation_shards = self._get_shards_from_relations(departed_shard_id)

            for shard in cluster_shards - relation_shards:
                self.charm.unit.status = MaintenanceStatus(f"Draining shard {shard}")
                logger.info("Attempting to removing shard: %s", shard)
                mongo.remove_shard(shard)
                logger.info("Attempting to removing shard: %s", shard)

    def _update_relation_data(self, relation_id: int, data: dict) -> None:
        """Updates a set of key-value pairs in the relation.

        This function writes in the application data bag, therefore, only the leader unit can call
        it.

        Args:
            relation_id: the identifier for a particular relation.
            data: dict containing the key-value pairs
                that should be updated in the relation.
        """
        if self.charm.unit.is_leader():
            relation = self.charm.model.get_relation(self.relation_name, relation_id)
            if relation:
                relation.data[self.charm.model.app].update(data)

    def _get_shards_from_relations(self, departed_shard_id: Optional[int]):
        """Returns a list of the shards related to the config-server."""
        relations = self.model.relations[self.relation_name]
        return set(
            [
                self._get_shard_name_from_relation(relation)
                for relation in relations
                if relation.id != departed_shard_id
            ]
        )

    def _get_shard_hosts(self, shard_name) -> str:
        """Retrieves the hosts for a specified shard."""
        relations = self.model.relations[self.relation_name]
        for relation in relations:
            if self._get_shard_name_from_relation(relation) == shard_name:
                return json.loads(relation.data[relation.app].get(HOSTS_KEY, "[]"))

    def _get_shard_name_from_relation(self, relation):
        """Returns the name of a shard for a specified relation."""
        return relation.app.name


class ConfigServerRequirer(Object):
    """Manage relations between the config server and the shard, on the shard's side."""

    def __init__(
        self, charm: CharmBase, relation_name: str = Config.Relations.SHARDING_RELATIONS_NAME
    ) -> None:
        """Constructor for ShardingProvider object."""
        self.relation_name = relation_name
        self.charm = charm

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            charm.on[self.relation_name].relation_departed, self._on_relation_departed
        )

        # TODO Future PR, enable shard drainage by observing relation departed events

    def _on_relation_changed(self, event):
        """Retrieves secrets from config-server and updates them within the shard."""
        if self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info(
                "skipping relation changed event ShardingProvider is only be executed by shards"
            )
            return

        if not self.charm.db_initialised:
            event.defer()

        # shards rely on the config server for secrets
        relation_data = event.relation.data[event.app]
        self.update_keyfile(key_file_contents=relation_data.get(KEYFILE_KEY))
        try:
            self.update_operator_password(new_password=relation_data.get(OPERATOR_PASSWORD_KEY))
        except RetryError:
            self.charm.unit.status = BlockedStatus("Shard not added to config-server")
            return

        self.charm.unit.status = MaintenanceStatus("Adding shard to config-server")

        if not self.charm.unit.is_leader():
            return

        # send hosts to mongos to be added to the cluster
        self._update_relation_data(
            event.relation.id,
            {HOSTS_KEY: json.dumps(self.charm._unit_ips)},
        )

        # TODO future PR, leader unit verifies shard was added to cluster (update-status hook)

    def _on_relation_departed(self, event) -> None:
        """Waits for the shard to be fully drained from the cluster."""
        if self.charm.is_role(Config.Role.REPLICATION):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error("sharding interface not supported with config role=replication")
            return

        if not self.charm.is_role(Config.Role.SHARD):
            logger.info(
                "skipping relation departed event ShardingProvider is only be executed by shards"
            )
            return

        if not self.charm.db_initialised:
            event.defer()
            return

        self.charm.unit.status = MaintenanceStatus("Draining shard from cluster")
        mongos_hosts = json.loads(event.relation.data[event.relation.app].get(HOSTS_KEY))
        drained = False
        while not drained:
            try:
                drained = self.drained(mongos_hosts, self.charm.app.name)
                logger.debug("Shards draining state: %s", drained)
                # no need to continuously check and abuse resources while shard is draining
                time.sleep(10)
            except PyMongoError as e:
                logger.error("Error occurred while draining shard: %s", e)
                self.charm.unit.status = BlockedStatus("Failed to drain shard from cluster")
            except ShardNotPlannedForRemovalError:
                logger.info(
                    "Shard %s has not been identifies for removal. Must wait for mongos cluster-admin to remove shard."
                )
            except ShardNotInClusterError:
                logger.info("Shard to remove, is not in sharded cluster.")
                break

        self.charm.unit.status = ActiveStatus("Shard drained from cluster, ready for removal")
        # TODO future PR, leader unit displays this message in update-status hook
        # TODO future PR, check for shard drainage when removing application

    def drained(self, mongos_hosts: Set[str], shard_name: str) -> bool:
        """Returns whether a shard has been drained from the cluster.

        Raises:
            ConfigurationError, OperationFailure, ShardNotInClusterError,
            ShardNotPlannedForRemovalError
        """
        if not self.charm.is_role(Config.Role.SHARD):
            logger.info(
                "Component %s is not a shard, cannot check draining status.", self.charm.role
            )
            return False

        if "draining" not in self.charm.app_peer_data and not self.charm.unit.is_leader():
            return False

        with MongosConnection(self.charm.remote_mongos_config(set(mongos_hosts))) as mongo:
            draining = mongo._is_shard_draining(shard_name)
            self.charm.app_peer_data["draining"] = json.dumps(draining)
            return self.charm.app_peer_data.get("draining")

    def update_operator_password(self, new_password: str) -> None:
        """Updates the password for the operator user.

        Raises:
            RetryError
        """
        current_password = (
            self.charm.get_secret(
                Config.Relations.APP_SCOPE, MongoDBUser.get_password_key_name_for_user("operator")
            ),
        )

        if not new_password or new_password == current_password or not self.charm.unit.is_leader():
            return

        # updating operator password, usually comes after keyfile was updated, hence, the mongodb
        # service was restarted. Sometimes this requires units getting insync again.
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
            with attempt:
                # TODO, in the future use set_password from src/charm.py - this will require adding
                # a library, for exceptions used in both charm code and lib code.
                with MongoDBConnection(self.charm.mongodb_config) as mongo:
                    try:
                        mongo.set_user_password(OperatorUser.get_username(), new_password)
                    except NotReadyError:
                        logger.error(
                            "Failed changing the password: Not all members healthy or finished initial sync."
                        )
                        raise
                    except PyMongoError as e:
                        logger.error(f"Failed changing the password: {e}")
                        raise

        self.charm.set_secret(
            Config.Relations.APP_SCOPE,
            MongoDBUser.get_password_key_name_for_user(OperatorUser.get_username()),
            new_password,
        )

    def update_keyfile(self, key_file_contents: str) -> None:
        """Updates keyfile on all units."""
        if not key_file_contents:
            return

        # put keyfile on the machine with appropriate permissions
        self.charm.push_file_to_unit(
            parent_dir=Config.MONGOD_CONF_DIR, file_name=KEY_FILE, file_contents=key_file_contents
        )

        # when the contents of the keyfile change, we must restart the service
        self.charm.restart_mongod_service()

        if not self.charm.unit.is_leader():
            return

        self.charm.set_secret(
            Config.Relations.APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME, key_file_contents
        )

    def _update_relation_data(self, relation_id: int, data: dict) -> None:
        """Updates a set of key-value pairs in the relation.

        This function writes in the application data bag, therefore, only the leader unit can call
        it.

        Args:
            relation_id: the identifier for a particular relation.
            data: dict containing the key-value pairs
                that should be updated in the relation.
        """
        if self.charm.unit.is_leader():
            relation = self.charm.model.get_relation(self.relation_name, relation_id)
            if relation:
                relation.data[self.charm.model.app].update(data)
