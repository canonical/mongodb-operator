#!/usr/bin/env python3
"""Charm code for MongoDB service."""
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
import subprocess
from subprocess import check_call, check_output
from typing import Dict, List, Optional

import ops.charm
from charms.mongodb.v0.helpers import (
    KEY_FILE,
    TLS_EXT_CA_FILE,
    TLS_EXT_PEM_FILE,
    TLS_INT_CA_FILE,
    TLS_INT_PEM_FILE,
    build_unit_status,
    generate_keyfile,
    generate_password,
    get_create_user_cmd,
)
from charms.mongodb.v0.mongodb import (
    CHARM_USERS,
    MongoDBConfiguration,
    MongoDBConnection,
    NotReadyError,
    PyMongoError,
)
from charms.mongodb.v0.mongodb_backups import S3_RELATION, MongoDBBackups
from charms.mongodb.v0.mongodb_provider import MongoDBProvider
from charms.mongodb.v0.mongodb_tls import MongoDBTLS
from charms.mongodb.v0.mongodb_vm_legacy_provider import MongoDBLegacyProvider
from charms.operator_libs_linux.v1 import snap
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    Relation,
    WaitingStatus,
)
from tenacity import Retrying, before_log, retry, stop_after_attempt, wait_fixed

from machine_helpers import DB_PROCESS, push_file_to_unit, update_mongod_service

logger = logging.getLogger(__name__)

PEER = "database-peers"
GPG_URL = "https://www.mongodb.org/static/pgp/server-5.0.asc"
MONGO_EXEC_LINE = 10
MONGO_USER = "snap_daemon"
MONGO_COMMON_DIR = "/var/snap/charmed-mongodb/common"
MONGO_DATA_DIR = f"{MONGO_COMMON_DIR}/db"
PBM_PRIVILEGES = {"resource": {"anyResource": True}, "actions": ["anyAction"]}
MONITOR_PRIVILEGES = {
    "resource": {"db": "", "collection": ""},
    "actions": ["listIndexes", "listCollections", "dbStats", "dbHash", "collStats", "find"],
}

# We expect the MongoDB container to use the default ports
MONGODB_PORT = 27017
SNAP_PACKAGES = [
    ("percona-backup-mongodb", "edge"),
    ("charmed-mongodb", "5.0/edge/pass-args"),
]
REL_NAME = "database"


class MongodbOperatorCharm(ops.charm.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self._port = MONGODB_PORT

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on[PEER].relation_joined, self._on_mongodb_relation_joined)
        self.framework.observe(self.on[PEER].relation_changed, self._on_mongodb_relation_handler)

        # if a new leader has been elected update hosts of MongoDB
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on[PEER].relation_departed, self._relation_departed)
        self.framework.observe(
            self.on.mongodb_storage_detaching, self._on_mongodb_storage_detaching
        )

        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.get_primary_action, self._on_get_primary_action)

        self.framework.observe(self.on.get_password_action, self._on_get_password)
        self.framework.observe(self.on.set_password_action, self._on_set_password)

        # handle provider side of relations
        self.client_relations = MongoDBProvider(self, substrate="vm")
        self.legacy_client_relations = MongoDBLegacyProvider(self)
        self.tls = MongoDBTLS(self, PEER, substrate="vm")
        self.backups = MongoDBBackups(self)

    def _generate_passwords(self) -> None:
        """Generate passwords and put them into peer relation.

        The same keyFile and admin password on all members needed, hence it is generated once and
        share between members via the app data.
        """
        if not self.get_secret("app", "operator-password"):
            self.set_secret("app", "operator-password", generate_password())

        if not self.get_secret("app", "keyfile"):
            self.set_secret("app", "keyfile", generate_keyfile())

    def _on_leader_elected(self, event) -> None:
        """Generates necessary keyfile and updates replica hosts."""
        if not self.get_secret("app", "keyfile"):
            self._generate_passwords()

        self._update_hosts(event)

        # app relations should be made aware of the new set of hosts
        try:
            self.update_app_relation_data()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _update_hosts(self, event) -> None:
        """Update replica set hosts and remove any unremoved replicas from the config."""
        if "db_initialised" not in self.app_peer_data:
            return

        self.process_unremoved_units(event)
        self.app_peer_data["replica_set_hosts"] = json.dumps(self._unit_ips)

    def _on_mongodb_storage_detaching(self, event: ops.charm.StorageDetachingEvent) -> None:
        """Before storage detaches, allow removing unit to remove itself from the set.

        If the removing unit is primary also allow it to step down and elect another unit as
        primary while it still has access to its storage.
        """
        # if we are removing the last replica it will not be able to step down as primary and we
        # cannot reconfigure the replica set to have 0 members. To prevent retrying for 10 minutes
        # set this flag to True. please note that planned_units will always be >=1. When planned
        # units is 1 that means there are no other peers expected.
        single_node_replica_set = self.app.planned_units() == 1 and len(self._peers.units) == 0
        if single_node_replica_set:
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

    def update_app_relation_data(self) -> None:
        """Helper function to update application relation data."""
        if "db_initialised" not in self.app_peer_data:
            return

        database_users = set()

        with MongoDBConnection(self.mongodb_config) as mongo:
            database_users = mongo.get_users()

        for relation in self.model.relations[REL_NAME]:
            username = self.client_relations._get_username_from_relation_id(relation.id)
            password = relation.data[self.app]["password"]
            config = self.client_relations._get_config(username, password)
            if username in database_users:
                data = relation.data[self.app]
                data["endpoints"] = ",".join(config.hosts)
                data["uris"] = config.uri
                relation.data[self.app].update(data)

    def _relation_departed(self, event: ops.charm.RelationDepartedEvent) -> None:
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
            self.update_app_relation_data()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def process_unremoved_units(self, event) -> None:
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

    def _on_mongodb_relation_joined(self, event: ops.charm.RelationJoinedEvent) -> None:
        """Add peer to replica set.

        Args:
            event: The triggering relation joined event.
        """
        if not self.unit.is_leader():
            return

        self._on_mongodb_relation_handler(event)

        # app relations should be made aware of the new set of hosts
        try:
            self.update_app_relation_data()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _on_mongodb_relation_handler(self, event: ops.charm.RelationEvent) -> None:
        """Adds the unit as a replica to the MongoDB replica set.

        Args:
            event: The triggering relation joined/changed event.
        """
        # only leader should configure replica set and app-changed-events can trigger the relation
        # changed hook resulting in no JUJU_REMOTE_UNIT if this is the case we should return
        # further reconfiguration can be successful only if a replica set is initialised.

        if (
            not (self.unit.is_leader() and event.unit)
            or "db_initialised" not in self.app_peer_data
        ):
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

    def _on_install(self, event) -> None:
        """Handle the install event (fired on startup)."""
        self.unit.status = MaintenanceStatus("installing MongoDB")
        try:
            self._install_snap_packages(packages=SNAP_PACKAGES)
        except snap.SnapError:
            self.unit.status = BlockedStatus("couldn't install MongoDB")

        # if a new unit is joining a cluster with a legacy relation it should start without auth
        auth = not self.client_relations._get_users_from_relations(None, rel="obsolete")

        # clear the default config file - user provided config files will be added in the config
        # hook
        check_output("truncate -s 0 /var/snap/charmed-mongodb/common/mongod.conf", shell=True)

        # Construct the mongod startup commandline args for systemd and reload the daemon.
        update_mongod_service(
            auth=auth, machine_ip=self._unit_ip(self.unit), config=self.mongodb_config
        )

    def _on_start(self, event: ops.charm.StartEvent) -> None:
        """Enables MongoDB service and initialises replica set.

        Args:
            event: The triggering start event.
        """
        # mongod requires keyFile and TLS certificates on the file system
        self._instatiate_keyfile(event)
        self._push_tls_certificate_to_workload()

        try:
            logger.debug("starting MongoDB.")
            self.unit.status = MaintenanceStatus("starting MongoDB")
            snap_cache = snap.SnapCache()
            mongodb_snap = snap_cache["charmed-mongodb"]
            mongodb_snap.start(services=["mongod"])
            self.unit.status = ActiveStatus()
        except snap.SnapError as e:
            logger.error("An exception occurred when starting mongod agent, error: %s.", str(e))
            self.unit.status = BlockedStatus("couldn't start MongoDB")
            return

        try:
            self._open_port_tcp(self._port)
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

        # only leader should initialise the replica set
        if not self.unit.is_leader():
            return

        self._initialise_replica_set(event)

    def _on_update_status(self, event):
        # cannot have both legacy and new relations since they have different auth requirements
        if self.client_relations._get_users_from_relations(
            None, rel="obsolete"
        ) and self.client_relations._get_users_from_relations(None):
            self.unit.status = BlockedStatus("cannot have both legacy and new relations")
            return

        # Occasionally mongod.service will try to restart too quickly leading to systemd not
        # being able to start the process at all. If this is the case we need to restart the
        # process ourselves. We defer to give it time to get started before reporting its
        # status.
        try:
            with MongoDBConnection(self.mongodb_config, "localhost", direct=True) as direct_mongo:
                if not direct_mongo.is_ready:
                    logger.debug("mongodb service is not ready yet, restarting.")
                    self.restart_mongod_service()
                    # ensure that the correct port is open for the service
                    self._open_port_tcp(self._port)
                    self.unit.status = WaitingStatus("Waiting for MongoDB to start")
                    event.defer()
                    return
        except snap.SnapError as e:
            logger.error("An exception occurred when starting mongod agent, error: %s.", str(e))
            self.unit.status = BlockedStatus("couldn't start MongoDB")
            return

        # no need to report on replica set status until initialised
        if "db_initialised" not in self.app_peer_data:
            return

        # leader should periodically handle configuring the replica set. Incidents such as network
        # cuts can lead to new IP addresses and therefore will require a reconfigure. Especially
        # in the case that the leader a change in IP address it will not receive a relation event.
        if self.unit.is_leader():
            self._handle_reconfigure(event)

        # update the units status based on it's replica set config and backup status. An error in
        # the status of MongoDB takes precedence over pbm status.
        mongodb_status = build_unit_status(self.mongodb_config, self._unit_ip(self.unit))
        pbm_status = self.backups._get_pbm_status()
        if (
            not isinstance(mongodb_status, ActiveStatus)
            or not self.model.get_relation(
                S3_RELATION
            )  # if s3 relation doesn't exist only report MongoDB status
            or isinstance(pbm_status, ActiveStatus)  # pbm is ready then report the MongoDB status
        ):
            self.unit.status = mongodb_status
        else:
            self.unit.status = pbm_status

    def _handle_reconfigure(self, event):
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
        self._on_mongodb_relation_handler(event)

        # app relations should be made aware of the new set of hosts
        try:
            self.update_app_relation_data()
        except PyMongoError as e:
            logger.error("Deferring on updating app relation data since: error: %r", e)
            event.defer()
            return

    def _on_get_primary_action(self, event: ops.charm.ActionEvent):
        event.set_results({"replica-set-primary": self._primary})

    def _on_get_password(self, event: ops.charm.ActionEvent) -> None:
        """Returns the password for the user as an action response."""
        username = event.params.get("username", "operator")
        if username not in CHARM_USERS:
            event.fail(
                f"The action can be run only for users used by the charm:"
                f" {', '.join(CHARM_USERS)} not {username}"
            )
            return

        event.set_results({"password": self.get_secret("app", f"{username}-password")})

    def _on_set_password(self, event: ops.charm.ActionEvent) -> None:
        """Set the password for the admin user."""
        # only leader can write the new password into peer relation.
        if not self.unit.is_leader():
            event.fail("The action can be run only on leader unit.")
            return

        username = event.params.get("username", "operator")
        if username not in CHARM_USERS:
            event.fail(
                f"The action can be run only for users used by the charm:"
                f" {', '.join(CHARM_USERS)} not {username}"
            )
            return

        new_password = generate_password()
        if "password" in event.params:
            new_password = event.params["password"]

        with MongoDBConnection(self.mongodb_config) as mongo:
            try:
                mongo.set_user_password(username, new_password)
            except NotReadyError:
                event.fail(
                    "Failed changing the password: Not all members healthy or finished initial sync."
                )
                return
            except PyMongoError as e:
                event.fail(f"Failed changing the password: {e}")
                return

        self.set_secret("app", f"{username}-password", new_password)
        event.set_results({"password": new_password})

    def _open_port_tcp(self, port: int) -> None:
        """Open the given port.

        Args:
            port: The port to open.
        """
        try:
            logger.debug("opening tcp port")
            check_call(["open-port", "{}/TCP".format(port)])
        except subprocess.CalledProcessError as e:
            logger.exception("failed opening port: %s", str(e))
            raise

    def _install_snap_packages(self, packages: List[str]) -> None:
        """Installs package(s) to container.

        Args:
            packages: list of packages to install.
        """
        for snap_name, snap_channel in packages:
            try:
                snap_cache = snap.SnapCache()
                snap_package = snap_cache[snap_name]

                if not snap_package.present:
                    snap_package.ensure(snap.SnapState.Latest, channel=snap_channel)

            except snap.SnapError as e:
                logger.error(
                    "An exception occurred when installing %s. Reason: %s", snap_name, str(e)
                )
                raise

    def _instatiate_keyfile(self, event: ops.charm.StartEvent) -> None:
        # wait for keyFile to be created by leader unit
        if not self.get_secret("app", "keyfile"):
            logger.debug("waiting for leader unit to generate keyfile contents")
            event.defer()
            return

        # put keyfile on the machine with appropriate permissions
        push_file_to_unit(
            parent_dir=MONGO_COMMON_DIR,
            file_name=KEY_FILE,
            file_contents=self.get_secret("app", "keyfile"),
        )

    def _push_tls_certificate_to_workload(self) -> None:
        """Uploads certificate to the workload container."""
        external_ca, external_pem = self.tls.get_tls_files("unit")
        if external_ca is not None:
            push_file_to_unit(
                parent_dir=MONGO_COMMON_DIR, file_name=TLS_EXT_CA_FILE, file_contents=external_ca
            )

        if external_pem is not None:
            push_file_to_unit(
                parent_dir=MONGO_COMMON_DIR, file_name=TLS_EXT_PEM_FILE, file_contents=external_pem
            )

        internal_ca, internal_pem = self.tls.get_tls_files("app")
        if internal_ca is not None:
            push_file_to_unit(
                parent_dir=MONGO_COMMON_DIR, file_name=TLS_INT_CA_FILE, file_contents=internal_ca
            )

        if internal_pem is not None:
            push_file_to_unit(
                parent_dir=MONGO_COMMON_DIR, file_name=TLS_INT_PEM_FILE, file_contents=internal_pem
            )

    def _initialise_replica_set(self, event: ops.charm.StartEvent) -> None:
        if "db_initialised" in self.app_peer_data:
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
                self._init_admin_user()
                self._init_backup_user()
                self._init_monitor_user()
                logger.info("Manage relations")
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
            self.app_peer_data["db_initialised"] = "True"
            self.unit.status = ActiveStatus()

    def _unit_ip(self, unit: ops.model.Unit) -> str:
        """Returns the ip address of a given unit."""
        # check if host is current host
        if unit == self.unit:
            return str(self.model.get_binding(PEER).network.bind_address)
        # check if host is a peer
        elif unit in self._peers.data:
            return str(self._peers.data[unit].get("private-address"))
        # raise exception if host not found
        else:
            raise ApplicationHostNotFoundError

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the secret storage."""
        if scope == "unit":
            return self.unit_peer_data.get(key, None)
        elif scope == "app":
            return self.app_peer_data.get(key, None)
        else:
            raise RuntimeError("Unknown secret scope.")

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> None:
        """Set secret in the secret storage."""
        if scope == "unit":
            if not value:
                del self.unit_peer_data[key]
                return
            self.unit_peer_data.update({key: str(value)})
        elif scope == "app":
            if not value:
                del self.app_peer_data[key]
                return
            self.app_peer_data.update({key: str(value)})
        else:
            raise RuntimeError("Unknown secret scope.")

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
    def mongodb_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for this deployment of MongoDB."""
        external_ca, _ = self.tls.get_tls_files("unit")
        internal_ca, _ = self.tls.get_tls_files("app")

        return MongoDBConfiguration(
            replset=self.app.name,
            database="admin",
            username="operator",
            password=self.get_secret("app", "operator-password"),
            hosts=set(self._unit_ips),
            roles={"default"},
            tls_external=external_ca is not None,
            tls_internal=internal_ca is not None,
        )

    @property
    def monitor_config(self) -> MongoDBConfiguration:
        """Generates a MongoDBConfiguration object for this deployment of MongoDB."""
        if not self.get_secret("app", "monitor-password"):
            self.set_secret("app", "monitor-password", generate_password())

        return MongoDBConfiguration(
            replset=self.app.name,
            database="",
            username="monitor",
            password=self.get_secret("app", "monitor-password"),
            hosts=set(self._unit_ips),
            roles={"monitor"},
            tls_external=self.tls.get_tls_files("unit") is not None,
            tls_internal=self.tls.get_tls_files("app") is not None,
        )

    @property
    def unit_peer_data(self) -> Dict:
        """Peer relation data object."""
        relation = self.model.get_relation(PEER)
        if relation is None:
            return {}

        return relation.data[self.unit]

    @property
    def app_peer_data(self) -> Dict:
        """Peer relation data object."""
        relation = self.model.get_relation(PEER)
        if not relation:
            return {}

        return relation.data[self.app]

    @property
    def _peers(self) -> Optional[Relation]:
        """Fetch the peer relation.

        Returns:
             An `ops.model.Relation` object representing the peer relation.
        """
        return self.model.get_relation(PEER)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _init_admin_user(self) -> None:
        """Creates initial admin user for MongoDB.

        Initial admin user can be created only through localhost connection.
        see https://www.mongodb.com/docs/manual/core/localhost-exception/
        unfortunately, pymongo unable to create connection that considered
        as local connection by MongoDB, even if socket connection used.
        As a result, where are only hackish ways to create initial user.
        It is needed to install mongodb-clients inside charm container to make
        this function work correctly.
        """
        if "user_created" in self.app_peer_data or not self.unit.is_leader():
            return

        out = subprocess.run(
            get_create_user_cmd(self.mongodb_config),
            input=self.mongodb_config.password.encode(),
        )
        if out.returncode == 0:
            raise AdminUserCreationError

        logger.debug("User created")
        self.app_peer_data["user_created"] = "True"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _init_monitor_user(self):
        """Creates the monitor user on the MongoDB database."""
        if "monitor_user_created" in self.app_peer_data:
            return

        with MongoDBConnection(self.mongodb_config) as mongo:
            logger.debug("creating the monitor user roles...")
            mongo.create_role(role_name="explainRole", privileges=MONITOR_PRIVILEGES)
            logger.debug("creating the monitor user...")
            mongo.create_user(self.monitor_config)
            self.app_peer_data["monitor_user_created"] = "True"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def _init_backup_user(self):
        """Creates the backup user on the MongoDB database."""
        if "backup_user_created" in self.app_peer_data:
            return

        with MongoDBConnection(self.mongodb_config) as mongo:
            # first we must create the necessary roles for the PBM tool
            logger.debug("creating the backup user roles...")
            mongo.create_role(role_name="pbmAnyAction", privileges=PBM_PRIVILEGES)
            logger.debug("creating the backup user...")
            mongo.create_user(self.backups._backup_config)
            self.app_peer_data["backup_user_created"] = "True"

    def restart_mongod_service(self, auth=None):
        """Restarts the mongod service with its associated configuration."""
        if auth is None:
            auth = self.auth_enabled()

        try:
            snap_cache = snap.SnapCache()
            mongodb_snap = snap_cache["charmed-mongodb"]
            mongodb_snap.stop(services=["mongod"])
            update_mongod_service(
                auth,
                self._unit_ip(self.unit),
                config=self.mongodb_config,
            )
            mongodb_snap.start(services=["mongod"])
        except snap.SnapError as e:
            logger.error("An exception occurred when starting mongod agent, error: %s.", str(e))
            self.unit.status = BlockedStatus("couldn't start MongoDB")
            return

    def auth_enabled(self) -> bool:
        """Checks if mongod service is has auth enabled for the current unit."""
        # Check if the current process that is running `mongod` has the auth flag
        output = check_output(f"ps aux | grep {DB_PROCESS}", shell=True)
        output = output.decode("utf-8")

        if "--auth" in output:
            return True

        return False


class AdminUserCreationError(Exception):
    """Raised when a commands to create an admin user on MongoDB fail."""

    pass


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""

    pass


if __name__ == "__main__":
    main(MongodbOperatorCharm)
