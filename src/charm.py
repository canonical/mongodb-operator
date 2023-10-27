#!/usr/bin/env python3
"""Charm code for MongoDB service."""
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
import os
import pwd
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.mongodb.v0.mongodb import (
    MongoDBConfiguration,
    MongoDBConnection,
    NotReadyError,
    PyMongoError,
)
from charms.mongodb.v0.mongodb_secrets import SecretCache, generate_secret_label
from charms.mongodb.v0.mongodb_tls import MongoDBTLS
from charms.mongodb.v1.helpers import (
    KEY_FILE,
    TLS_EXT_CA_FILE,
    TLS_EXT_PEM_FILE,
    TLS_INT_CA_FILE,
    TLS_INT_PEM_FILE,
    build_unit_status,
    copy_licenses_to_unit,
    generate_keyfile,
    generate_password,
    get_create_user_cmd,
)
from charms.mongodb.v1.mongodb_backups import S3_RELATION, MongoDBBackups
from charms.mongodb.v1.mongodb_provider import MongoDBProvider
from charms.mongodb.v1.mongodb_vm_legacy_provider import MongoDBLegacyProvider
from charms.mongodb.v1.mongos import MongosConfiguration
from charms.mongodb.v1.shards_interface import ConfigServerRequirer, ShardingProvider
from charms.mongodb.v1.users import (
    CHARM_USERS,
    BackupUser,
    MongoDBUser,
    MonitorUser,
    OperatorUser,
)
from charms.operator_libs_linux.v1 import snap
from ops.charm import (
    ActionEvent,
    CharmBase,
    ConfigChangedEvent,
    InstallEvent,
    LeaderElectedEvent,
    RelationDepartedEvent,
    RelationEvent,
    RelationJoinedEvent,
    SecretChangedEvent,
    SecretRemoveEvent,
    StartEvent,
    StorageDetachingEvent,
    UpdateStatusEvent,
)
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    StatusBase,
    Unit,
    WaitingStatus,
)
from tenacity import Retrying, before_log, retry, stop_after_attempt, wait_fixed

from config import Config
from exceptions import AdminUserCreationError, ApplicationHostNotFoundError
from machine_helpers import MONGO_USER, ROOT_USER_GID, update_mongod_service

logger = logging.getLogger(__name__)

APP_SCOPE = Config.Relations.APP_SCOPE
UNIT_SCOPE = Config.Relations.UNIT_SCOPE
Scopes = Config.Relations.Scopes


class MongodbOperatorCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self._port = Config.MONGODB_PORT

        # lifecycle events
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(
            self.on[Config.Relations.PEERS].relation_joined, self._on_relation_joined
        )
        self.framework.observe(
            self.on[Config.Relations.PEERS].relation_changed, self._on_relation_handler
        )
        self.framework.observe(
            self.on[Config.Relations.PEERS].relation_departed, self._on_relation_departed
        )

        # if a new leader has been elected update hosts of MongoDB
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.mongodb_storage_detaching, self._on_storage_detaching)

        # actions
        self.framework.observe(self.on.get_primary_action, self._on_get_primary_action)
        self.framework.observe(self.on.get_password_action, self._on_get_password)
        self.framework.observe(self.on.set_password_action, self._on_set_password)

        # secrets
        self.framework.observe(self.on.secret_remove, self._on_secret_remove)
        self.framework.observe(self.on.secret_changed, self._on_secret_changed)

        # handle provider side of relations
        self.client_relations = MongoDBProvider(self, substrate=Config.SUBSTRATE)
        self.legacy_client_relations = MongoDBLegacyProvider(self)
        self.tls = MongoDBTLS(self, Config.Relations.PEERS, substrate=Config.SUBSTRATE)
        self.backups = MongoDBBackups(self)
        self.config_server = ShardingProvider(self)
        self.shard = ConfigServerRequirer(self)

        # relation events for Prometheus metrics are handled in the MetricsEndpointProvider
        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=Config.Monitoring.METRICS_ENDPOINTS,
            metrics_rules_dir=Config.Monitoring.METRICS_RULES_DIR,
            logs_rules_dir=Config.Monitoring.LOGS_RULES_DIR,
            log_slots=Config.Monitoring.LOG_SLOTS,
        )

        self.secrets = SecretCache(self)

    # BEGIN: properties

    @property
    def _primary(self) -> str:
        """Retrieves the unit with the primary replica."""
        try:
            with MongoDBConnection(self.mongodb_config) as mongo:
                primary_ip = mongo.primary()
        except PyMongoError as e:
            logger.error("Unable to access primary due to: %s", e)
            return None

        # check if current unit matches primary ip
        if primary_ip == self._unit_ip(self.unit):
            return self.unit.name

        # check if peer unit matches primary ip
        for unit in self._peers.units:
            if primary_ip == self._unit_ip(unit):
                return unit.name

        return None

    @property
    def drained(self) -> bool:
        """Returns whether the shard has been drained."""
        if not self.is_role(Config.Role.SHARD):
            logger.info("Component %s is not a shard, cannot check draining status.", self.role)
            return False

        return self.app_peer_data.get("drained", False)

    @property
    def _unit_ips(self) -> List[str]:
        """Retrieve IP addresses associated with MongoDB application.

        Returns:
            a list of IP address associated with MongoDB application.
        """
        peer_addresses = []
        if self._peers:
            peer_addresses = [self._unit_ip(unit) for unit in self._peers.units]

        logger.debug("peer addresses: %s", peer_addresses)
        self_address = self._unit_ip(self.unit)
        logger.debug("unit address: %s", self_address)
        addresses = []
        if peer_addresses:
            addresses.extend(peer_addresses)
        addresses.append(self_address)
        return addresses

    @property
    def _replica_set_hosts(self):
        """Fetch current list of hosts in the replica set.

        Returns:
            A list of hosts addresses (strings).
        """
        return json.loads(self.app_peer_data.get("replica_set_hosts", "[]"))

    @property
    def mongos_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for mongos in the deployment of MongoDB."""
        return self._get_mongos_config_for_user(OperatorUser, set(self._unit_ips))

    def remote_mongos_config(self, hosts) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for mongos in the deployment of MongoDB."""
        # mongos that are part of the cluster have the same username and password, but different
        # hosts
        return self._get_mongos_config_for_user(OperatorUser, hosts)

    @property
    def mongodb_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for this deployment of MongoDB."""
        return self._get_mongodb_config_for_user(OperatorUser, set(self._unit_ips))

    @property
    def monitor_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for monitoring."""
        return self._get_mongodb_config_for_user(MonitorUser, MonitorUser.get_hosts())

    @property
    def backup_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for backup."""
        self._check_or_set_user_password(BackupUser)
        return self._get_mongodb_config_for_user(BackupUser, BackupUser.get_hosts())

    @property
    def unit_peer_data(self) -> Dict:
        """Peer relation data object."""
        if not self._peers:
            return {}

        return self._peers.data[self.unit]

    @property
    def app_peer_data(self) -> Dict:
        """Peer relation data object."""
        if not self._peers:
            return {}

        return self._peers.data[self.app]

    @property
    def _peers(self) -> Optional[Relation]:
        """Fetch the peer relation.

        Returns:
             An `ops.model.Relation` object representing the peer relation.
        """
        return self.model.get_relation(Config.Relations.PEERS)

    @property
    def db_initialised(self) -> bool:
        """Check if MongoDB is initialised."""
        return "db_initialised" in self.app_peer_data

    @property
    def role(self) -> str:
        """Returns role of MongoDB deployment."""
        if (
            "role" not in self.app_peer_data
            and self.unit.is_leader()
            and self.model.config["role"]
        ):
            self.app_peer_data["role"] = self.model.config["role"]
            # app data bag isn't set until function completes
            return self.model.config["role"]
        elif "role" not in self.app_peer_data:
            # if leader hasn't set the role yet, use the one set by model
            return self.model.config["role"]

        return self.app_peer_data.get("role")

    def is_role_changed(self) -> bool:
        """Checks if application is running in provided role."""
        return self.role != self.model.config["role"]

    def is_role(self, role_name: str) -> bool:
        """Checks if application is running in provided role."""
        return self.role == role_name

    @db_initialised.setter
    def db_initialised(self, value):
        """Set the db_initialised flag."""
        if isinstance(value, bool):
            self.app_peer_data["db_initialised"] = str(value)
        else:
            raise ValueError(
                f"'db_initialised' must be a boolean value. Proivded: {value} is of type {type(value)}"
            )

    # END: properties

    # BEGIN: charm event handlers

    def _on_install(self, event: InstallEvent) -> None:
        """Handle the install event (fired on startup)."""
        self.unit.status = MaintenanceStatus("installing MongoDB")
        try:
            self._install_snap_packages(packages=Config.SNAP_PACKAGES)

        except snap.SnapError:
            self.unit.status = BlockedStatus("couldn't install MongoDB")
            return

        # if a new unit is joining a cluster with a legacy relation it should start without auth
        auth = not self.client_relations._get_users_from_relations(
            None, rel=Config.Relations.OBSOLETE_RELATIONS_NAME
        )

        # clear the default config file - user provided config files will be added in the config
        # changed hook
        try:
            with open(Config.MONGOD_CONF_FILE_PATH, "r+") as f:
                f.truncate(0)
        except IOError:
            self.unit.status = BlockedStatus("Could not install MongoDB")
            return

        # Construct the mongod startup commandline args for systemd and reload the daemon.
        update_mongod_service(
            auth=auth,
            machine_ip=self._unit_ip(self.unit),
            config=self.mongodb_config,
            role=self.role,
        )

        # add licenses
        copy_licenses_to_unit()

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Listen to changes in application configuration.

        To prevent a user from migrating a cluster, and causing the component to become
        unresponsive therefore causing a cluster failure, error the component. This prevents it
        from executing other hooks with a new role.
        """
        # TODO in the future (24.04) support migration of components
        if self.is_role_changed():
            logger.error(
                f"cluster migration currently not supported, cannot change from { self.model.config['role']} to {self.role}"
            )
            raise ShardingMigrationError(
                f"Migration of sharding components not permitted, revert config role to {self.role}"
            )

    def _on_start(self, event: StartEvent) -> None:
        """Enables MongoDB service and initialises replica set.

        Args:
            event: The triggering start event.
        """
        # mongod requires keyFile and TLS certificates on the file system
        self._instatiate_keyfile(event)
        self.push_tls_certificate_to_workload()

        try:
            logger.debug("starting MongoDB.")
            self.unit.status = MaintenanceStatus("starting MongoDB")
            self.start_mongod_service()
            self.unit.status = ActiveStatus()
        except snap.SnapError as e:
            logger.error("An exception occurred when starting mongod agent, error: %s.", str(e))
            self.unit.status = BlockedStatus("couldn't start MongoDB")
            return

        try:
            ports = [self._port]
            if self.is_role(Config.Role.CONFIG_SERVER):
                ports.append(Config.MONGOS_PORT)

            self._open_ports_tcp(ports)
        except subprocess.CalledProcessError:
            self.unit.status = BlockedStatus("failed to open TCP port for MongoDB")
            return

        # check if this unit's deployment of MongoDB is ready
        with MongoDBConnection(self.mongodb_config, "localhost", direct=True) as direct_mongo:
            if not direct_mongo.is_ready:
                logger.debug("mongodb service is not ready yet.")
                self.unit.status = WaitingStatus("waiting for MongoDB to start")
                event.defer()
                return

        # mongod is now active
        self.unit.status = ActiveStatus()

        try:
            self._connect_mongodb_exporter()
        except snap.SnapError as e:
            logger.error(
                "An exception occurred when starting mongodb exporter, error: %s.", str(e)
            )
            self.unit.status = BlockedStatus("couldn't start mongodb exporter")
            return

        # only leader should initialise the replica set
        if not self.unit.is_leader():
            return

        self._initialise_replica_set(event)

    def _on_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Add peer to replica set.

        Args:
            event: The triggering relation joined event.
        """
        if not self.unit.is_leader():
            return

        self._on_relation_handler(event)

        # app relations should be made aware of the new set of hosts
        try:
            self.client_relations.update_app_relation_data()
            self.config_server.update_mongos_hosts()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _on_relation_handler(self, event: RelationEvent) -> None:
        """Adds the unit as a replica to the MongoDB replica set.

        Args:
            event: The triggering relation joined/changed event.
        """
        # changing the monitor password will lead to non-leader units receiving a relation changed
        # event. We must update the monitor and pbm URI if the password changes so that COS/pbm
        # can continue to work
        self._connect_mongodb_exporter()
        self._connect_pbm_agent()

        # only leader should configure replica set and app-changed-events can trigger the relation
        # changed hook resulting in no JUJU_REMOTE_UNIT if this is the case we should return
        # further reconfiguration can be successful only if a replica set is initialised.
        if not (self.unit.is_leader() and event.unit) or not self.db_initialised:
            return

        with MongoDBConnection(self.mongodb_config) as mongo:
            try:
                replset_members = mongo.get_replset_members()
                # compare set of mongod replica set members and juju hosts to avoid the unnecessary
                # reconfiguration.
                if replset_members == self.mongodb_config.hosts:
                    return

                for member in self.mongodb_config.hosts - replset_members:
                    logger.debug("Adding %s to replica set", member)
                    with MongoDBConnection(
                        self.mongodb_config, member, direct=True
                    ) as direct_mongo:
                        if not direct_mongo.is_ready:
                            self.unit.status = WaitingStatus("waiting to reconfigure replica set")
                            logger.debug("Deferring reconfigure: %s is not ready yet.", member)
                            event.defer()
                            return
                    mongo.add_replset_member(member)
                    self.unit.status = ActiveStatus()
            except NotReadyError:
                self.unit.status = WaitingStatus("waiting to reconfigure replica set")
                logger.error("Deferring reconfigure: another member doing sync right now")
                event.defer()
            except PyMongoError as e:
                self.unit.status = WaitingStatus("waiting to reconfigure replica set")
                logger.error("Deferring reconfigure: error=%r", e)
                event.defer()

    def _on_leader_elected(self, event: LeaderElectedEvent) -> None:
        """Generates necessary keyfile and updates replica hosts."""
        if not self.get_secret(APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME):
            self._generate_secrets()

        self._update_hosts(event)

        # app relations should be made aware of the new set of hosts
        try:
            self.client_relations.update_app_relation_data()
            self.config_server.update_mongos_hosts()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _on_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Remove peer from replica set if it wasn't able to remove itself.

        Args:
            event: The triggering relation departed event.
        """
        # allow leader to update relation data and hosts if it isn't leaving
        if not self.unit.is_leader() or event.departing_unit == self.unit:
            return

        self._update_hosts(event)

        # app relations should be made aware of the new set of hosts
        try:
            self.client_relations.update_app_relation_data()
            self.config_server.update_mongos_hosts()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _on_storage_detaching(self, event: StorageDetachingEvent) -> None:
        """Before storage detaches, allow removing unit to remove itself from the set.

        If the removing unit is primary also allow it to step down and elect another unit as
        primary while it still has access to its storage.
        """
        # A single replica cannot step down as primary and we cannot reconfigure the replica set to
        # have 0 members.
        if self._is_removing_last_replica:
            # removing config-server from a sharded cluster can be disaterous.
            if self.is_role(Config.Role.CONFIG_SERVER) and self.config_server.has_shards():
                current_shards = self.config_server.get_related_shards()
                early_removal_message = f"Cannot remove config-server, still related to shards {', '.join(current_shards)}"
                logger.error(early_removal_message)
                raise EarlyRemovalOfConfigServerError(early_removal_message)

            # cannot drain shard after storage detached.
            if self.is_role(Config.Role.SHARD) and self.shard.has_config_server():
                logger.info("Wait for shard to drain before detaching storage.")
                self.unit.status = MaintenanceStatus("Draining shard from cluster")
                mongos_hosts = self.shard.get_mongos_hosts()
                self.shard.wait_for_draining(mongos_hosts)
                logger.info("Shard successfully drained storage.")

            return

        try:
            # retries over a period of 10 minutes in an attempt to resolve race conditions it is
            # not possible to defer in storage detached.
            logger.debug("Removing %s from replica set", self._unit_ip(self.unit))
            for attempt in Retrying(
                stop=stop_after_attempt(10),
                wait=wait_fixed(1),
                reraise=True,
            ):
                with attempt:
                    # remove_replset_member retries for 60 seconds
                    with MongoDBConnection(self.mongodb_config) as mongo:
                        mongo.remove_replset_member(self._unit_ip(self.unit))
        except NotReadyError:
            logger.info(
                "Failed to remove %s from replica set, another member is syncing", self.unit.name
            )
        except PyMongoError as e:
            logger.error("Failed to remove %s from replica set, error=%r", self.unit.name, e)

    def _on_update_status(self, event: UpdateStatusEvent):
        # cannot have both legacy and new relations since they have different auth requirements
        if self.client_relations._get_users_from_relations(
            None, rel="obsolete"
        ) and self.client_relations._get_users_from_relations(None):
            self.unit.status = BlockedStatus("cannot have both legacy and new relations")
            return

        # no need to report on replica set status until initialised
        if not self.db_initialised:
            return

        # Cannot check more advanced MongoDB statuses if mongod hasn't started.
        with MongoDBConnection(self.mongodb_config, "localhost", direct=True) as direct_mongo:
            if not direct_mongo.is_ready:
                self.unit.status = WaitingStatus("Waiting for MongoDB to start")
                return

        # leader should periodically handle configuring the replica set. Incidents such as network
        # cuts can lead to new IP addresses and therefore will require a reconfigure. Especially
        # in the case that the leader a change in IP address it will not receive a relation event.
        if self.unit.is_leader():
            self._handle_reconfigure(event)

        self.unit.status = self.get_status()

    def _on_get_primary_action(self, event: ActionEvent):
        event.set_results({"replica-set-primary": self._primary})

    def _on_get_password(self, event: ActionEvent) -> None:
        """Returns the password for the user as an action response."""
        username = self._get_user_or_fail_event(
            event, default_username=OperatorUser.get_username()
        )
        if not username:
            return
        key_name = MongoDBUser.get_password_key_name_for_user(username)
        event.set_results(
            {Config.Actions.PASSWORD_PARAM_NAME: self.get_secret(APP_SCOPE, key_name)}
        )

    def _on_set_password(self, event: ActionEvent) -> None:
        """Set the password for the admin user."""
        # check conditions for setting the password and fail if necessary
        if not self.pass_pre_set_password_checks(event):
            return

        username = self._get_user_or_fail_event(
            event, default_username=OperatorUser.get_username()
        )
        if not username:
            return

        new_password = event.params.get(Config.Actions.PASSWORD_PARAM_NAME, generate_password())
        if len(new_password) > Config.Secrets.MAX_PASSWORD_LENGTH:
            event.fail(
                f"Password cannot be longer than {Config.Secrets.MAX_PASSWORD_LENGTH} characters."
            )
            return

        try:
            secret_id = self.set_password(username, new_password)
        except SetPasswordError as e:
            event.fail(e)
            return

        if username == BackupUser.get_username():
            self._connect_pbm_agent()

        if username == MonitorUser.get_username():
            self._connect_mongodb_exporter()

        # rotate password to shards
        # TODO in the future support rotating passwords of pbm across shards
        if username == OperatorUser.get_username():
            self.config_server.update_credentials(
                MongoDBUser.get_password_key_name_for_user(username),
                new_password,
            )

        event.set_results(
            {Config.Actions.PASSWORD_PARAM_NAME: new_password, "secret-id": secret_id}
        )

    def set_password(self, username, password) -> int:
        """Sets the password for a given username and return the secret id.

        Raises:
            SetPasswordError
        """
        with MongoDBConnection(self.mongodb_config) as mongo:
            try:
                mongo.set_user_password(username, password)
            except NotReadyError:
                raise SetPasswordError(
                    "Failed changing the password: Not all members healthy or finished initial sync."
                )
            except PyMongoError as e:
                raise SetPasswordError(f"Failed changing the password: {e}")

        return self.set_secret(
            APP_SCOPE, MongoDBUser.get_password_key_name_for_user(username), password
        )

    def _on_secret_remove(self, event: SecretRemoveEvent):
        # We are keeping this function empty on purpose until the issue with secrets
        # is not fixed. The issue is: https://bugs.launchpad.net/juju/+bug/2023364
        logging.error(
            f"_on_secret_remove: Secret {event._id} seems to have no observers, could be removed"
        )

    def _on_secret_changed(self, event: SecretChangedEvent):
        """Handles secrets changes event.

        When user run set-password action, juju leader changes the password inside the database
        and inside the secret object. This action runs the restart for monitoring tool and
        for backup tool on non-leader units to keep them working with MongoDB. The same workflow
        occurs on TLS certs change.
        """
        label = None
        if generate_secret_label(self, Config.Relations.APP_SCOPE) == event.secret.label:
            label = generate_secret_label(self, Config.Relations.APP_SCOPE)
            scope = APP_SCOPE
        elif generate_secret_label(self, Config.Relations.UNIT_SCOPE) == event.secret.label:
            label = generate_secret_label(self, Config.Relations.UNIT_SCOPE)
            scope = UNIT_SCOPE
        else:
            logging.debug("Secret %s changed, but it's unknown", event.secret.id)
            return
        logging.debug("Secret %s for scope %s changed, refreshing", event.secret.id, scope)

        # Refreshing cache
        self.secrets.get(label)

        # changed secrets means that the URIs used for PBM and mongodb_exporter are now out of date
        self._connect_mongodb_exporter()
        self._connect_pbm_agent()

    # END: charm event handlers

    # BEGIN: users management

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _init_operator_user(self) -> None:
        """Creates initial admin user for MongoDB.

        Initial admin user can be created only through localhost connection.
        see https://www.mongodb.com/docs/manual/core/localhost-exception/
        unfortunately, pymongo unable to create connection that considered
        as local connection by MongoDB, even if socket connection used.
        As a result, where are only hackish ways to create initial user.
        It is needed to install mongodb-clients inside charm container to make
        this function work correctly.
        """
        if self._is_user_created(OperatorUser) or not self.unit.is_leader():
            return

        out = subprocess.run(
            get_create_user_cmd(self.mongodb_config),
            input=self.mongodb_config.password.encode(),
        )
        if out.returncode == 0:
            raise AdminUserCreationError

        logger.debug(f"{OperatorUser.get_username()} user created")
        self._set_user_created(OperatorUser)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _init_monitor_user(self):
        """Creates the monitor user on the MongoDB database."""
        if self._is_user_created(MonitorUser):
            return

        with MongoDBConnection(self.mongodb_config) as mongo:
            logger.debug("creating the monitor user roles...")
            mongo.create_role(
                role_name=MonitorUser.get_mongodb_role(), privileges=MonitorUser.get_privileges()
            )
            logger.debug("creating the monitor user...")
            mongo.create_user(self.monitor_config)
            self._set_user_created(MonitorUser)

        # leader should reconnect to exporter after creating the monitor user - since the snap
        # will have an authorisation error until the the user has been created and the daemon
        # has been restarted
        self._connect_mongodb_exporter()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _init_backup_user(self):
        """Creates the backup user on the MongoDB database."""
        if self._is_user_created(BackupUser):
            return

        with MongoDBConnection(self.mongodb_config) as mongo:
            # first we must create the necessary roles for the PBM tool
            logger.debug("creating the backup user roles...")
            mongo.create_role(
                role_name=BackupUser.get_mongodb_role(), privileges=BackupUser.get_privileges()
            )
            logger.debug("creating the backup user...")
            mongo.create_user(self.backup_config)
            self._set_user_created(BackupUser)

    # END: users management

    # BEGIN: helper functions
    def _is_user_created(self, user: MongoDBUser) -> bool:
        return f"{user.get_username()}-user-created" in self.app_peer_data

    def _set_user_created(self, user: MongoDBUser) -> None:
        self.app_peer_data[f"{user.get_username()}-user-created"] = "True"

    def _get_mongos_config_for_user(
        self, user: MongoDBUser, hosts: Set[str]
    ) -> MongosConfiguration:
        external_ca, _ = self.tls.get_tls_files(UNIT_SCOPE)
        internal_ca, _ = self.tls.get_tls_files(APP_SCOPE)

        return MongosConfiguration(
            database=user.get_database_name(),
            username=user.get_username(),
            password=self.get_secret(APP_SCOPE, user.get_password_key_name()),
            hosts=hosts,
            port=Config.MONGOS_PORT,
            roles=user.get_roles(),
            tls_external=external_ca is not None,
            tls_internal=internal_ca is not None,
        )

    def _get_mongodb_config_for_user(
        self, user: MongoDBUser, hosts: Set[str]
    ) -> MongoDBConfiguration:
        external_ca, _ = self.tls.get_tls_files(UNIT_SCOPE)
        internal_ca, _ = self.tls.get_tls_files(APP_SCOPE)

        return MongoDBConfiguration(
            replset=self.app.name,
            database=user.get_database_name(),
            username=user.get_username(),
            password=self.get_secret(APP_SCOPE, user.get_password_key_name()),
            hosts=hosts,
            roles=user.get_roles(),
            tls_external=external_ca is not None,
            tls_internal=internal_ca is not None,
        )

    def _get_user_or_fail_event(self, event: ActionEvent, default_username: str) -> Optional[str]:
        """Returns MongoDBUser object or raises ActionFail if user doesn't exist."""
        username = event.params.get(Config.Actions.USERNAME_PARAM_NAME, default_username)
        if username not in CHARM_USERS:
            event.fail(
                f"The action can be run only for users used by the charm:"
                f" {', '.join(CHARM_USERS)} not {username}"
            )
            return
        return username

    def pass_pre_set_password_checks(self, event: ActionEvent) -> bool:
        """Checks conditions for setting the password and fail if necessary."""
        if self.is_role(Config.Role.SHARD):
            event.fail("Cannot set password on shard, please set password on config-server.")
            return

        # changing the backup password while a backup/restore is in progress can be disastrous
        pbm_status = self.backups.get_pbm_status()
        if isinstance(pbm_status, MaintenanceStatus):
            event.fail("Cannot change password while a backup/restore is in progress.")
            return

        # only leader can write the new password into peer relation.
        if not self.unit.is_leader():
            event.fail("The action can be run only on leader unit.")
            return

        return True

    def _check_or_set_user_password(self, user: MongoDBUser) -> None:
        key = user.get_password_key_name()
        if not self.get_secret(APP_SCOPE, key):
            self.set_secret(APP_SCOPE, key, generate_password())

    def _generate_secrets(self) -> None:
        """Generate secrets and put them into peer relation.

        The same keyFile and admin password on all members needed, hence it is generated once and
        share between members via the app data.
        """
        self._check_or_set_user_password(OperatorUser)
        self._check_or_set_user_password(MonitorUser)

        if not self.get_secret(APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME):
            self.set_secret(APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME, generate_keyfile())

    def _update_hosts(self, event: LeaderElectedEvent) -> None:
        """Update replica set hosts and remove any unremoved replicas from the config."""
        if not self.db_initialised:
            return

        self.process_unremoved_units(event)
        self.app_peer_data["replica_set_hosts"] = json.dumps(self._unit_ips)

    def process_unremoved_units(self, event: LeaderElectedEvent) -> None:
        """Removes replica set members that are no longer running as a juju hosts."""
        with MongoDBConnection(self.mongodb_config) as mongo:
            try:
                replset_members = mongo.get_replset_members()
                for member in replset_members - self.mongodb_config.hosts:
                    logger.debug("Removing %s from replica set", member)
                    mongo.remove_replset_member(member)
            except NotReadyError:
                logger.info("Deferring process_unremoved_units: another member is syncing")
                event.defer()
            except PyMongoError as e:
                logger.error("Deferring process_unremoved_units: error=%r", e)
                event.defer()

    def _handle_reconfigure(self, event: UpdateStatusEvent):
        """Reconfigures the replica set if necessary.

        Removes any mongod hosts that are no longer present in the replica set or adds hosts that
        should exist in the replica set. This function is meant to be called periodically by the
        leader in the update status hook to perform any necessary cluster healing.
        """
        if not self.unit.is_leader():
            logger.debug("only the leader can perform reconfigurations to the replica set.")
            return

        # remove any IPs that are no longer juju hosts & update app data.
        self._update_hosts(event)
        # Add in any new IPs to the replica set. Relation handlers require a reference to
        # a unit.
        event.unit = self.unit
        self._on_relation_handler(event)

        # app relations should be made aware of the new set of hosts
        try:
            self.client_relations.update_app_relation_data()
            self.config_server.update_mongos_hosts()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _open_ports_tcp(self, ports: int) -> None:
        """Open the given port.

        Args:
            ports: The ports to open.
        """
        for port in ports:
            try:
                logger.debug("opening tcp port")
                subprocess.check_call(["open-port", "{}/TCP".format(port)])
            except subprocess.CalledProcessError as e:
                logger.exception("failed opening port: %s", str(e))
                raise

    def _install_snap_packages(self, packages: List[str]) -> None:
        """Installs package(s) to container.

        Args:
            packages: list of packages to install.
        """
        for snap_name, snap_channel, snap_revision in packages:
            try:
                snap_cache = snap.SnapCache()
                snap_package = snap_cache[snap_name]
                snap_package.ensure(
                    snap.SnapState.Latest, channel=snap_channel, revision=snap_revision
                )
                # snaps will auto refresh so it is necessary to hold the current revision
                snap_package.hold()

            except snap.SnapError as e:
                logger.error(
                    "An exception occurred when installing %s. Reason: %s", snap_name, str(e)
                )
                raise

    def _instatiate_keyfile(self, event: StartEvent) -> None:
        # wait for keyFile to be created by leader unit
        if not self.get_secret(APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME):
            logger.debug("waiting for leader unit to generate keyfile contents")
            event.defer()
            return

        # put keyfile on the machine with appropriate permissions
        self.push_file_to_unit(
            parent_dir=Config.MONGOD_CONF_DIR,
            file_name=KEY_FILE,
            file_contents=self.get_secret(APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME),
        )

    def get_keyfile_contents(self) -> str:
        """Retrieves the contents of the keyfile on host machine."""
        # wait for keyFile to be created by leader unit
        if not self.get_secret(APP_SCOPE, Config.Secrets.SECRET_KEYFILE_NAME):
            logger.debug("waiting for leader unit to generate keyfile contents")
            return

        key_file_path = f"{Config.MONGOD_CONF_DIR}/{KEY_FILE}"
        key_file = Path(key_file_path)
        if not key_file.is_file():
            logger.info("no keyfile present")
            return

        with open(key_file_path, "r") as file:
            key = file.read()

        return key

    def push_file_to_unit(self, parent_dir, file_name, file_contents) -> None:
        """K8s charms can push files to their containers easily, this is a vm charm workaround."""
        Path(parent_dir).mkdir(parents=True, exist_ok=True)
        file_name = f"{parent_dir}/{file_name}"
        with open(file_name, "w") as write_file:
            write_file.write(file_contents)

        # MongoDB limitation; it is needed 400 rights for keyfile and we need 440 rights on tls
        # certs to be able to connect via MongoDB shell
        if Config.TLS.KEY_FILE_NAME in file_name:
            os.chmod(file_name, 0o400)
        else:
            os.chmod(file_name, 0o440)
        mongodb_user = pwd.getpwnam(MONGO_USER)
        os.chown(file_name, mongodb_user.pw_uid, ROOT_USER_GID)

    def remove_file_from_unit(self, parent_dir, file_name) -> None:
        """Remove file from vm unit."""
        if os.path.exists(f"{parent_dir}/{file_name}"):
            os.remove(f"{parent_dir}/{file_name}")

    def push_tls_certificate_to_workload(self) -> None:
        """Uploads certificate to the workload container."""
        external_ca, external_pem = self.tls.get_tls_files(UNIT_SCOPE)
        if external_ca is not None:
            self.push_file_to_unit(
                parent_dir=Config.MONGOD_CONF_DIR,
                file_name=TLS_EXT_CA_FILE,
                file_contents=external_ca,
            )

        if external_pem is not None:
            self.push_file_to_unit(
                parent_dir=Config.MONGOD_CONF_DIR,
                file_name=TLS_EXT_PEM_FILE,
                file_contents=external_pem,
            )

        internal_ca, internal_pem = self.tls.get_tls_files(APP_SCOPE)
        if internal_ca is not None:
            self.push_file_to_unit(
                parent_dir=Config.MONGOD_CONF_DIR,
                file_name=TLS_INT_CA_FILE,
                file_contents=internal_ca,
            )

        if internal_pem is not None:
            self.push_file_to_unit(
                parent_dir=Config.MONGOD_CONF_DIR,
                file_name=TLS_INT_PEM_FILE,
                file_contents=internal_pem,
            )

    def delete_tls_certificate_from_workload(self) -> None:
        """Deletes certificate from VM."""
        logger.info("Deleting TLS certificate from VM")

        for file in [
            Config.TLS.EXT_CA_FILE,
            Config.TLS.EXT_PEM_FILE,
            Config.TLS.INT_CA_FILE,
            Config.TLS.INT_PEM_FILE,
        ]:
            self.remove_file_from_unit(Config.MONGOD_CONF_DIR, file)

    def _connect_mongodb_exporter(self) -> None:
        """Exposes the endpoint to mongodb_exporter."""
        if not self.db_initialised:
            return

        # must wait for leader to set URI before connecting
        if not self.get_secret(APP_SCOPE, MonitorUser.get_password_key_name()):
            return

        snap_cache = snap.SnapCache()
        mongodb_snap = snap_cache["charmed-mongodb"]
        mongodb_snap.set({Config.Monitoring.URI_PARAM_NAME: self.monitor_config.uri})
        mongodb_snap.restart(services=[Config.Monitoring.SERVICE_NAME])

    def _connect_pbm_agent(self) -> None:
        """Updates URI for pbm-agent."""
        if not self.db_initialised:
            return

        # must wait for leader to set URI before any attempts to update are made
        if not self.get_secret(APP_SCOPE, BackupUser.get_password_key_name()):
            return

        snap_cache = snap.SnapCache()
        pbm_snap = snap_cache["charmed-mongodb"]
        pbm_snap.stop(services=[Config.Backup.SERVICE_NAME])
        pbm_snap.set({Config.Backup.URI_PARAM_NAME: self.backup_config.uri})
        try:
            # Added to avoid systemd error:
            # 'snap.charmed-mongodb.pbm-agent.service: Start request repeated too quickly'
            time.sleep(1)
            pbm_snap.start(services=[Config.Backup.SERVICE_NAME], enable=True)
        except snap.SnapError as e:
            logger.error(f"Failed to restart {Config.Backup.SERVICE_NAME}: {str(e)}")
            self._get_service_status(Config.Backup.SERVICE_NAME)
            raise e

    def _get_service_status(self, service_name) -> None:
        logger.error(f"Getting status of {service_name} service:")
        self._run_diagnostic_command(
            f"systemctl status snap.charmed-mongodb.{service_name}.service"
        )
        self._run_diagnostic_command(
            f"journalctl -xeu snap.charmed-mongodb.{service_name}.service"
        )

    def _run_diagnostic_command(self, cmd) -> None:
        logger.error("Running diagnostic command: %s", cmd)
        try:
            output = subprocess.check_output(cmd, shell=True, text=True)
            logger.error(output)
        except subprocess.CalledProcessError as e:
            logger.error(f"Exception occurred running '{cmd}'\n {e}")

    def _initialise_replica_set(self, event: StartEvent) -> None:
        if self.db_initialised:
            # The replica set should be initialised only once. Check should be
            # external (e.g., check initialisation inside peer relation). We
            # shouldn't rely on MongoDB response because the data directory
            # can be corrupted.
            return

        with MongoDBConnection(self.mongodb_config, "localhost", direct=True) as direct_mongo:
            try:
                logger.info("Replica Set initialization")
                direct_mongo.init_replset()
                self._peers.data[self.app]["replica_set_hosts"] = json.dumps(
                    [self._unit_ip(self.unit)]
                )

                logger.info("User initialization")
                self._init_operator_user()
                self._init_backup_user()
                self._init_monitor_user()

                # in sharding, user management is handled by mongos subordinate charm
                if self.is_role(Config.Role.REPLICATION):
                    logger.info("Manage user")
                    self.client_relations.oversee_users(None, None)

            except subprocess.CalledProcessError as e:
                logger.error(
                    "Deferring on_start: exit code: %i, stderr: %s", e.exit_code, e.stderr
                )
                event.defer()
                self.unit.status = WaitingStatus("waiting to initialise replica set")
                return
            except PyMongoError as e:
                logger.error("Deferring on_start since: error=%r", e)
                event.defer()
                self.unit.status = WaitingStatus("waiting to initialise replica set")
                return

            # replica set initialised properly and ready to go
            self.db_initialised = True
            self.unit.status = ActiveStatus()

    def _unit_ip(self, unit: Unit) -> str:
        """Returns the ip address of a given unit."""
        # check if host is current host
        if unit == self.unit:
            return str(self.model.get_binding(Config.Relations.PEERS).network.bind_address)
        # check if host is a peer
        elif unit in self._peers.data:
            return str(self._peers.data[unit].get("private-address"))
        # raise exception if host not found
        else:
            raise ApplicationHostNotFoundError

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the secret storage."""
        label = generate_secret_label(self, scope)
        secret = self.secrets.get(label)
        if not secret:
            return

        value = secret.get_content().get(key)
        if value != Config.Secrets.SECRET_DELETED_LABEL:
            return value

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> Optional[str]:
        """Set secret in the secret storage.

        Juju versions > 3.0 use `juju secrets`, this function first checks
          which secret store is being used before setting the secret.
        """
        if not value:
            return self.remove_secret(scope, key)

        label = generate_secret_label(self, scope)
        secret = self.secrets.get(label)
        if not secret:
            self.secrets.add(label, {key: value}, scope)
        else:
            content = secret.get_content()
            content.update({key: value})
            secret.set_content(content)
        return label

    def remove_secret(self, scope, key) -> None:
        """Removing a secret."""
        label = generate_secret_label(self, scope)
        secret = self.secrets.get(label)

        if not secret:
            return

        content = secret.get_content()

        if not content.get(key) or content[key] == Config.Secrets.SECRET_DELETED_LABEL:
            logger.error(f"Non-existing secret {scope}:{key} was attempted to be removed.")
            return

        content[key] = Config.Secrets.SECRET_DELETED_LABEL
        secret.set_content(content)

    def start_mongod_service(self):
        """Starts the mongod service and if necessary starts mongos.

        Raises:
            snap.SnapError
        """
        snap_cache = snap.SnapCache()
        mongodb_snap = snap_cache["charmed-mongodb"]
        mongodb_snap.start(services=["mongod"], enable=True)

        # charms running as config server are responsible for maintaining a server side mongos
        if self.is_role(Config.Role.CONFIG_SERVER):
            mongodb_snap.start(services=["mongos"], enable=True)

    def stop_mongod_service(self):
        """Stops the mongod service and if necessary stops mongos.

        Raises:
            snap.SnapError
        """
        snap_cache = snap.SnapCache()
        mongodb_snap = snap_cache["charmed-mongodb"]
        mongodb_snap.stop(services=["mongod"])

        # charms running as config server are responsible for maintaining a server side mongos
        if self.is_role(Config.Role.CONFIG_SERVER):
            mongodb_snap.stop(services=["mongos"])

    def restart_mongod_service(self, auth=None):
        """Restarts the mongod service with its associated configuration."""
        if auth is None:
            auth = self.auth_enabled()

        try:
            self.stop_mongod_service()
            update_mongod_service(
                auth,
                self._unit_ip(self.unit),
                config=self.mongodb_config,
                role=self.role,
            )
            self.start_mongod_service()
        except snap.SnapError as e:
            logger.error("An exception occurred when starting mongod agent, error: %s.", str(e))
            self.unit.status = BlockedStatus("couldn't start MongoDB")
            return

    def auth_enabled(self) -> bool:
        """Returns true is a mongod service has the auth configuration."""
        with open(Config.ENV_VAR_PATH, "r") as env_vars_file:
            env_vars = env_vars_file.readlines()

        return any("MONGOD_ARGS" in line and "--auth" in line for line in env_vars)

    def has_backup_service(self):
        """Verifies the backup service is available."""
        snap_cache = snap.SnapCache()
        mongodb_snap = snap_cache["charmed-mongodb"]
        if mongodb_snap.present:
            return True

        return False

    def clear_pbm_config_file(self) -> None:
        """Overwrites existing config file with the default file provided by snap."""
        subprocess.check_output(
            f"charmed-mongodb.pbm config --file {Config.MONGODB_SNAP_DATA_DIR}/etc/pbm/pbm_config.yaml",
            shell=True,
        )

    def run_pbm_command(self, cmd: List[str]) -> str:
        """Executes the provided pbm command.

        Raises:
            subprocess.CalledProcessError
        """
        pbm_response = subprocess.check_output(f"charmed-mongodb.pbm {' '.join(cmd)}", shell=True)
        return pbm_response.decode("utf-8")

    def start_backup_service(self) -> None:
        """Starts the pbm agent.

        Raises:
            snap.SnapError
        """
        snap_cache = snap.SnapCache()
        charmed_mongodb_snap = snap_cache["charmed-mongodb"]
        charmed_mongodb_snap.start(services=["pbm-agent"], enable=True)

    def restart_backup_service(self) -> None:
        """Restarts the pbm agent.

        Raises:
            snap.SnapError
        """
        snap_cache = snap.SnapCache()
        charmed_mongodb_snap = snap_cache["charmed-mongodb"]
        charmed_mongodb_snap.restart(services=["pbm-agent"])

    def _scope_obj(self, scope: Scopes):
        if scope == APP_SCOPE:
            return self.app
        if scope == UNIT_SCOPE:
            return self.unit

    def _peer_data(self, scope: Scopes):
        if not self._peers:
            return {}.setdefault(scope, {})
        scope_obj = self._scope_obj(scope)
        return self._peers.data[scope_obj]

    def check_relation_broken_or_scale_down(self, event: RelationDepartedEvent) -> None:
        """Checks relation departed event is the result of removed relation or scale down.

        Relation departed and relation broken events occur during scaling down or during relation
        removal, only relation departed events have access to metadata to determine which case.
        """
        self.set_scaling_down(event)

        if self.is_scaling_down(event.relation.id):
            logger.info(
                "Scaling down the application, no need to process removed relation in broken hook."
            )

    def is_scaling_down(self, rel_id: int) -> bool:
        """Returns True if the application is scaling down."""
        rel_departed_key = self._generate_relation_departed_key(rel_id)
        return json.loads(self.unit_peer_data[rel_departed_key])

    def has_departed_run(self, rel_id: int) -> bool:
        """Returns True if the relation departed event has run."""
        rel_departed_key = self._generate_relation_departed_key(rel_id)
        return rel_departed_key in self.unit_peer_data

    def set_scaling_down(self, event: RelationDepartedEvent) -> None:
        """Sets whether or not the current unit is scaling down."""
        # check if relation departed is due to current unit being removed. (i.e. scaling down the
        # application.)
        rel_departed_key = self._generate_relation_departed_key(event.relation.id)
        self.unit_peer_data[rel_departed_key] = json.dumps(event.departing_unit == self.unit)

    @staticmethod
    def _generate_relation_departed_key(rel_id: int) -> str:
        """Generates the relation departed key for a specified relation id."""
        return f"relation_{rel_id}_departed"

    @property
    def _is_removing_last_replica(self) -> bool:
        """Returns True if the last replica (juju unit) is getting removed."""
        return self.app.planned_units() == 0 and len(self._peers.units) == 0

    def get_status(self) -> StatusBase:
        """Returns the status with the highest priority from backups, sharding, and mongod.

        Note: it will never be the case that shard_status and config_server_status are both present
        since the mongodb app can either be a shard or a config server, but not both.
        """
        # retrieve statuses of different services running on Charmed MongoDB
        mongodb_status = build_unit_status(self.mongodb_config, self._unit_ip(self.unit))
        shard_status = self.shard.get_shard_status() if self.is_role(Config.Role.SHARD) else None
        config_server_status = (
            self.config_server.get_config_server_status()
            if self.is_role(Config.Role.CONFIG_SERVER)
            else None
        )
        pbm_status = (
            self.backups.get_pbm_status() if self.model.get_relation(S3_RELATION) else None
        )

        # failure in mongodb takes precedence over sharding and config server
        if not isinstance(mongodb_status, ActiveStatus):
            return mongodb_status

        if shard_status and not isinstance(shard_status, ActiveStatus):
            return shard_status

        if config_server_status and not isinstance(config_server_status, ActiveStatus):
            return config_server_status

        if pbm_status and not isinstance(pbm_status, ActiveStatus):
            return pbm_status

        # if all statuses are active report sharding statuses over mongodb status
        if isinstance(shard_status, ActiveStatus):
            return shard_status

        if isinstance(config_server_status, ActiveStatus):
            return config_server_status

        return mongodb_status

    def is_relation_feasible(self, rel_interface) -> bool:
        """Returns true if the proposed relation is feasible."""
        if self.is_sharding_component() and rel_interface in Config.Relations.DB_RELATIONS:
            self.unit.status = BlockedStatus(
                f"Sharding roles do not support {rel_interface} interface."
            )
            logger.error(
                "Charm is in sharding role: %s. Does not support %s interface.",
                rel_interface,
                self.role,
            )
            return False

        if (
            not self.is_sharding_component()
            and rel_interface != Config.Relations.SHARDING_RELATIONS_NAME
        ):
            self.unit.status = BlockedStatus("role replication does not support sharding")
            logger.error(
                "Charm is in sharding role: %s. Does not support %s interface.",
                self.role,
                rel_interface,
            )
            return False

        return True

    def is_sharding_component(self) -> bool:
        """Returns true if charm is running as a sharded component."""
        return self.is_role(Config.Role.SHARD) or self.is_role(Config.Role.CONFIG_SERVER)

    # END: helper functions


class ShardingMigrationError(Exception):
    """Raised when there is an attempt to change the role of a sharding component."""


class SetPasswordError(Exception):
    """Raised on failure to set password for MongoDB user."""


class EarlyRemovalOfConfigServerError(Exception):
    """Raised when there is an attempt to remove a config-server, while related to a shard."""


if __name__ == "__main__":
    main(MongodbOperatorCharm)
