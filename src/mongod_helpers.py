"""Code for facilitating interaction with mongod for a juju unit running MongoDB."""
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import Dict, List

from bson.json_util import dumps
from pymongo import MongoClient
from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    OperationFailure,
    PyMongoError,
)
from tenacity import (
    RetryError,
    before_log,
    retry,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    wait_fixed,
)

logger = logging.getLogger(__name__)

# We expect the MongoDB container to use the
# default ports
MONGODB_PORT = 27017


class NotReadyError(PyMongoError):
    """Raised when not all replica set members healthy or finished initial sync."""


class MongoDB:
    """Communicate with mongod using pymongo python package."""

    def __init__(self, config):
        self._app_name = config["app_name"]
        self._replica_set_name = config["replica_set_name"]
        self._num_hosts = config["num_hosts"]
        self._port = config["port"]
        self._root_password = config["root_password"]
        self._unit_ips = config["unit_ips"]
        self._replica_set_hosts = config["replica_set_hosts"]
        self._calling_unit_ip = config["calling_unit_ip"]

    def client(self, standalone=False) -> MongoClient:
        """Construct a client for the MongoDB database.

        The timeout for all queries using this client object is 1 sec.

        Args:
            standalone: an optional boolean flag that indicates if the client should connect to a
            single instance of MongoDB or the entire replica set
        Returns:
            A pymongo `MongoClient` object.
        """
        if self._calling_unit_ip == "localhost":
            return MongoClient(
                "localhost",
                directConnection=True,
                connect=False,
                serverSelectionTimeoutMS=1000,
                connectTimeoutMS=2000,
            )
        return MongoClient(self.replica_uri(standalone), serverSelectionTimeoutMS=1000)

    @retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=30))
    def check_server_info(self, client: MongoClient):
        """Repeatedly checks to see if the server is ready, timing out after 10 tries.

        Args:
            client: MongoClient client to check for server info.

        Returns:
            client.server_info information about the server.
        """
        try:
            client.server_info()
        except Exception as e:
            logger.debug(e)
            raise e

    def check_replica_status(self, replica_ip) -> str:
        """Retrieves the status of replica.

        Args:
            replica_ip: ip of replica to check status of
        """
        # connect to mongod and retrieve replica set status
        client = self.client(standalone=True)
        try:
            status = client.admin.command("replSetGetStatus")
            logger.debug("current replica set status: %s", status)
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            logger.error("Failed to check the replica status, error: %s", e)
            raise
        finally:
            client.close()

        # look for our ip address in set of members
        for member in status["members"]:
            # get member ip without ":PORT"
            member_ip = member["name"].split(":")[0]
            logger.debug(member_ip)
            if replica_ip == member_ip:
                return member["stateStr"]

        return None

    def member_ips(self):
        """Returns IP addresses of current replicas."""
        # grab the replica set status
        client = self.client()
        try:
            status = client.admin.command("replSetGetStatus")
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            raise e
        finally:
            client.close()

        hosts = [self._hostname_from_hostport(member["name"]) for member in status["members"]]

        return hosts

    @staticmethod
    def _is_any_removing(rs_status: Dict) -> bool:
        """Returns true if any replica set members are being removed.

        Checks if any members in replica set are getting removed. It is recommended to run only one
        removal in the cluster at a time as to not have huge performance degradation.

        Args:
            rs_status: current state of replica set as reported by mongod.
        """
        return any(member["stateStr"] == "REMOVED" for member in rs_status["members"])

    def all_replicas_ready(self) -> bool:
        """Returns true if all replica hosts are ready."""
        for unit_ip in self._replica_set_hosts:
            if not self.is_replica_ready(unit_ip):
                logger.debug("unit: %s is not ready", unit_ip)
                return False

        return True

    def is_replica_ready(self, replica_ip=None) -> bool:
        """Is the MongoDB replica in the ready state.

        Args:
            replica_ip: optional, ip of replica to query.

        Returns:
            bool: True if services is ready False otherwise.
        """
        # use _calling_unit_ip if no specific replica is given
        if not replica_ip:
            replica_ip = self._calling_unit_ip

        try:
            replica_status = self.check_replica_status(replica_ip)
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            logger.error("failed to attain replica status error: %s", e)
            return False

        logger.debug("replica status for replica: %s is: %s", replica_ip, replica_status)
        if (
            replica_status == "PRIMARY"
            or replica_status == "SECONDARY"
            or replica_status == "ARBITER"
        ):
            return True

        return False

    def is_mongod_ready(self) -> bool:
        """Are mongod services available on a single replica.

        Returns:
            bool: True if services is ready False otherwise.
        """
        ready = False
        client = self.client(standalone=True)

        try:
            self.check_server_info(client)
            ready = True
        except RetryError as e:
            logger.debug("mongod.service is not ready yet. %s", e)
        finally:
            client.close()
        return ready

    def is_replica_set(self) -> bool:
        """Is the MongoDB server operating as a replica set.

        Returns:
            bool: True if server is operating as a replica set False otherwise.
        """
        is_replica_set = False

        # cannot be in replica set status if this server is not up
        if not self.is_mongod_ready():
            return is_replica_set

        # access instance replica set configuration
        client = self.client(standalone=True)

        collection = client.local.system.replset
        try:
            replica_set_name = collection.find()[0]["_id"]
            logger.debug("replica set exists with name: %s", replica_set_name)
            is_replica_set = True
        except IndexError:
            logger.debug("replica set not yet initialised")
        finally:
            client.close()

        return is_replica_set

    def primary(self):
        """Returns IP address of current replica set primary."""
        # grab the replica set status
        client = self.client()
        try:
            status = client.admin.command("replSetGetStatus")
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            raise e
        finally:
            client.close()

        primary = None
        # loop through all members in the replica set
        for member in status["members"]:
            # check replica's current state
            if member["stateStr"] == "PRIMARY":
                # get member ip without ":PORT"
                primary = member["name"].split(":")[0]

        return primary

    def _is_primary(self, rs_status: Dict, hostname: str) -> bool:
        """Returns True if passed host is the replica set primary.

        Args:
            hostname: host of interest.
            rs_status: current state of replica set as reported by mongod.
        """
        return any(
            hostname == self._hostname_from_hostport(member["name"])
            and member["stateStr"] == "PRIMARY"
            for member in rs_status["members"]
        )

    def primary_step_down(self) -> None:
        """Steps primary replica down, enabling one of the secondaries to become primary."""
        client = self.client()
        try:
            config = {"stepDownSecs": "60"}
            client.admin.command("replSetStepDown", config)
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            raise e
        finally:
            client.close()

    def initialise_replica_set(self, hosts: list) -> None:
        """Initialize the MongoDB replica set.

        Args:
            hosts: a list of peer host addresses.
        """
        config = {
            "_id": self._replica_set_name,
            "members": [{"_id": i, "host": h} for i, h in enumerate(hosts)],
        }
        logger.debug("setting up replica set with these options %s", config)

        # must initiate replica with current unit IP address
        client = self.client(standalone=True)
        try:
            client.admin.command("replSetInitiate", config)
        except ConnectionFailure as e:
            logger.error(
                "cannot initialise replica set: failure to connect to mongo client: error: %s",
                str(e),
            )
            raise e
        except ConfigurationError as e:
            logger.error("cannot initialise replica set: incorrect credentials: error: %s", str(e))
            raise e
        except OperationFailure as e:
            if e.code not in (13, 23):  # Unauthorized, AlreadyInitialized
                # Unauthorized error can be raised only if initial user were
                #     created the step after this.
                # AlreadyInitialized error can be raised only if this step
                #     finished.
                logger.error(
                    "cannot initialise replica set: database operation failed: error: %s", str(e)
                )
                raise e
        finally:
            client.close()

    @retry(
        stop=stop_after_delay(60),
        wait=wait_fixed(5),
        reraise=True,
        before=before_log(logger, logging.DEBUG),
    )
    def remove_replset_member(self, hostname: str) -> None:
        """Remove member from replica set config inside MongoDB and steps down primary if needed.

        Raises:
            ConfigurationError, ConfigurationError, OperationFailure, NotReadyError
        """
        client = self.client()

        rs_config = client.admin.command("replSetGetConfig")
        rs_status = client.admin.command("replSetGetStatus")

        # To avoid issues when a majority of replica set members are removed, only remove a member
        # if no other members are being removed.
        if self._is_any_removing(rs_status):
            # removing from replicaset is fast operation, lets @retry(for one minute with a 5s
            # second delay) before giving up.
            logger.debug("one or more units are currently removing")
            raise NotReadyError

        # avoid downtime we need to reelect new primary if removable member is the primary.
        logger.debug("primary: %r", self._is_primary(rs_status, hostname))
        if self._is_primary(rs_status, hostname):
            logger.debug("setting down primary")
            client.admin.command("replSetStepDown", {"stepDownSecs": "60"})

        # if multiple units are removing at the same time, they will have conflicting config
        # versions and `replSetReconfig` operation will fail leading us to @retry. This ensures
        # thread safe execution.
        rs_config["config"]["version"] += 1
        rs_config["config"]["members"][:] = [
            member
            for member in rs_config["config"]["members"]
            if hostname != self._hostname_from_hostport(member["host"])
        ]
        logger.debug("rs_config: %r", dumps(rs_config["config"]))
        client.admin.command("replSetReconfig", rs_config["config"])
        client.close()

    def reconfigure_replica_set(self) -> None:
        """Reconfigure the MongoDB replica set.

        Using the current MongoDB configuration from mongod, reconfigure_replica_set reconfigures
        the replica set based on the current replica set hosts and the desired replica set hosts.
        """
        replica_set_client = self.client()
        try:
            # get current configuration and update with correct hosts
            rs_config = replica_set_client.admin.command("replSetGetConfig")
            rs_config["config"]["_id"] = self._replica_set_name
            rs_config["config"]["members"] = self.replica_set_config(rs_config)
            rs_config["config"]["version"] += 1
            replica_set_client.admin.command("replSetReconfig", rs_config["config"])
        except ConnectionFailure as e:
            logger.error(
                "cannot reconfigure replica set: failure to connect to mongo client: error: %s",
                str(e),
            )
            raise e
        except ConfigurationError as e:
            logger.error(
                "cannot reconfigure replica set: incorrect credentials: error: %s", str(e)
            )
            raise e
        except OperationFailure as e:
            logger.error(
                "cannot reconfigure replica set: database operation failed: error: %s", str(e)
            )
            raise e
        finally:
            replica_set_client.close()

    def replica_set_config(self, rs_config) -> List[dict]:
        """Maps unit ips to MongoDB replica set ids.

        When reconfiguring a replica set it is a requirement of mongod that machines do not get
        reassigned to different replica ids. This function ensures that already assigned machines
        maintain their replica set id and that new machines get assigned a new unused id.

        Args:
            rs_config: dict containing current configuration of replica set according to mongod

        Returns:
            A list of dicts, where each dict contains the host machine with its replica set id
        """
        new_config = []

        # acquire current members in config
        current_members = rs_config["config"]["members"]
        logger.debug("current config for replica set: %s", current_members)

        # look at each member in the current config and decide if it belongs in the new confg
        used_ids = set()
        assigned_ips = set()
        for member in current_members:
            # get member ip without ":PORT"
            member_ip = member["host"].split(":")[0]

            # if this ip is still being used retain it in new config
            if member_ip in self._unit_ips:
                new_config.append(member)
                used_ids.add(int(member["_id"]))
                assigned_ips.add(member_ip)

        # assign un-assigned ips with un-used ids if possible
        unassigned_ips = set(self._unit_ips).difference(assigned_ips)
        unused_ids = set(range(0, self._num_hosts)).difference(used_ids)

        # create new ids if necessary
        if len(unused_ids) == 0:
            unused_ids = range(self._num_hosts, self._num_hosts + len(unassigned_ips))

        # get current configuration
        new_assignments = [
            {"_id": i, "host": (h + ":" + str(self._port))}
            for i, h in zip(unused_ids, unassigned_ips)
        ]
        new_config.extend(new_assignments)

        # return new config
        logger.debug("new config for replica set: %s", new_config)
        return new_config

    def replica_uri(self, standalone=False, credentials=None) -> str:
        """Construct a replica set URI.

        Args:
            credentials: an optional dictionary with keys "username" and "password".
            standalone: an optional boolean flag that indicates if the uri should use the full
            replica set or a stand

        Returns:
            A string URI that may be used to access the MongoDB
            replica set.
        """
        uri = "mongodb://"
        if not standalone:
            hosts = ["{}:{}".format(unit_ip, self._port) for unit_ip in self._unit_ips]
            hosts += ",".join(hosts)
        else:
            hosts += "{}:{}".format(self._calling_unit_ip, self._port)

        uri = (
            f"mongodb://operator:"
            f"{self._root_password}@"
            f"{hosts}/admin"
            f"replicaSet={self._replica_set_name}"
        )

        logger.debug("uri %s", uri)
        return uri

    @staticmethod
    def _hostname_from_hostport(hostname: str) -> str:
        """Returns parsed host from MongoDB replica set hostname.

        For hostnames MongoDB typically returns a value that contains both, hostname and port.
        This function parses the host from this.
        e.g. input: mongodb-1:27015
             output: mongodb-1
        """
        return hostname.split(":")[0]
