# Copyright 2021 Canonical Ltd
# See LICENSE file for licensing details.

import logging

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ConfigurationError
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# We expect the MongoDB container to use the
# default ports
MONGODB_PORT = 27017


class MongoDB:
    def __init__(self, config):
        self._app_name = config["app_name"]
        self._replica_set_name = config["replica_set_name"]
        self._num_peers = config["num_peers"]
        self._port = config["port"]
        self._root_password = config["root_password"]
        self._unit_ips = config["unit_ips"]
        self._calling_unit_ip = config["calling_unit_ip"]

    def client(self, all_replicas=True) -> MongoClient:
        """Construct a client for the MongoDB database.

        The timeout for all queries using this client object is 1 sec.

        Args:
            all_replicas: an optional boolean flag that indicates if the client
            should connect to the full replica set or a single replica
        Returns:
            A pymongo `MongoClient` object.
        """
        return MongoClient(self.replica_uri(all_replicas), serverSelectionTimeoutMS=1000)

    @retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=30))
    def check_server_info(self, client: MongoClient):
        """Repeatly checks to see if the server is ready, timing out after 10 tries.

        Args:
            client: MongoClient client to check for server info.
        Returns:
            client.server_info information about the server.
        """
        return client.server_info()

    def is_ready(self, all_replicas=True) -> bool:
        """Is the MongoDB server ready to services requests.

        Args:
            all_replicas: an optional boolean flag that indicates if the client
            should check if the full replica set or a single replica is ready
        Returns:
            bool: True if services is ready False otherwise.
        """
        ready = False
        client = self.client(all_replicas)
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

        Args:
            None
        Returns:
            bool: True if server is operating as a replica set False otherwise.
        """
        is_replica_set = False

        # cannot be in replica set status if this server is not up
        if not self.is_ready(all_replicas=False):
            return is_replica_set

        # access instance replica set configuration
        client = self.client(all_replicas=False)
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
        client = self.client(all_replicas=False)
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
        finally:
            client.close()

    def replica_uri(self, all_replicas=True, credentials=None) -> str:
        """Construct a replica set URI.

        Args:
            credentials: an optional dictionary with keys "username"
            and "password".
            all_replicas: an optional boolean flag that indicates if the uri
            should use the full replica set or a single replica

        Returns:
            A string URI that may be used to access the MongoDB
            replica set.
        """
        if credentials:
            password = credentials["password"]
            username = credentials["username"]
        else:
            password = self._root_password
            username = "root"

        # TODO add password configuration in future patch
        # uri = "mongodb://{}:{}@".format(
        #    username,
        #    password)

        uri = "mongodb://"
        if all_replicas:
            for i, host in enumerate(self._unit_ips):
                if i:
                    uri += ","
                uri += "{}:{}".format(host, self._port)
        else:
            uri += "{}:{}".format(self._calling_unit_ip, self._port)

        uri += "/"
        logger.debug("uri %s", uri)
        return uri
