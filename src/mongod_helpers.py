"""Code for facilitating interaction with mongod for a juju unit running MongoDB."""
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import List

from pymongo import MongoClient
from pymongo.errors import ConfigurationError, ConnectionFailure, OperationFailure
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# We expect the MongoDB container to use the
# default ports
MONGODB_PORT = 27017


class MongoDB:
    """Communicate with mongod using pymongo python package."""

    def __init__(self, config):
        self._app_name = config["app_name"]
        self._replica_set_name = config["replica_set_name"]
        self._num_hosts = config["num_hosts"]
        self._port = config["port"]
        self._root_password = config["root_password"]
        self._unit_ips = config["unit_ips"]
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
        return MongoClient(self.replica_uri(standalone), serverSelectionTimeoutMS=1000)

    @retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=30))
    def check_server_info(self, client: MongoClient):
        """Repeatedly checks to see if the server is ready, timing out after 10 tries.

        Args:
            client: MongoClient client to check for server info.

        Returns:
            client.server_info information about the server.
        """
        return client.server_info()

    def check_replica_status(self) -> str:
        """Retrieves the status of the current replica."""
        # connect to mongod and retrieve replica set status
        client = self.client(standalone=True)
        try:
            status = client.admin.command("replSetGetStatus")
        except (ConnectionFailure, ConfigurationError, OperationFailure) as e:
            logger.error("Failed to check the replica status, error: %s", e)
            raise e
        finally:
            client.close()

        # look for our ip address in set of members
        for member in status["members"]:
            # get member ip without ":PORT"
            if self._calling_unit_ip == member["name"].split(":")[0]:
                return member["stateStr"]

        return None

    def is_replica_ready(self) -> bool:
        """Is the MongoDB replica in the ready state.

        Returns:
            bool: True if services is ready False otherwise.
        """
        try:
            replica_status = self.check_replica_status()
        except (ConnectionFailure, ConfigurationError, OperationFailure):
            return False

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
            logger.error(
                "cannot initialise replica set: database operation failed: error: %s", str(e)
            )
            raise e
        finally:
            client.close()

    def remove_replica(self, remove_replica_ip: str) -> None:
        """Removes the replica with remove_replica_ip from the MongoDB replica set config.

        Using the current MongoDB configuration from mongod, remove_replica reconfigures the
        replica set such that it no longer contains the replica with remove_replica_ip.

        Args:
            remove_replica_ip: the ip of the replica to remove.
        """
        replica_set_client = self.client()
        try:
            # get current configuration and update with correct hosts
            rs_config = replica_set_client.admin.command("replSetGetConfig")
            rs_config["config"]["version"] += 1

            # acquire current members in config
            current_members = rs_config["config"]["members"]
            logger.debug("current config for replica set: %s", current_members)
            new_members = []

            # add members to new config that aren't getting removed
            for member in current_members:
                # get member ip without ":PORT"
                member_ip = member["host"].split(":")[0]

                # if this ip is still being used retain it in new config
                if member_ip != remove_replica_ip:
                    new_members.append(member)

            rs_config["config"]["members"] = new_members
            replica_set_client.admin.command("replSetReconfig", rs_config["config"])
        except (ConfigurationError, ConfigurationError, OperationFailure):
            raise
        finally:
            replica_set_client.close()

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
        # TODO add password configuration in future patch

        uri = "mongodb://"
        if not standalone:
            hosts = ["{}:{}".format(unit_ip, self._port) for unit_ip in self._unit_ips]
            uri += ",".join(hosts)
        else:
            uri += "{}:{}".format(self._calling_unit_ip, self._port)

        uri += "/"
        logger.debug("uri %s", uri)
        return uri
