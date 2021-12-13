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

    def client(self) -> MongoClient:
        """Construct a client for the MongoDB database.

        The timeout for all queries using this client object is 1 sec.

        Returns:
            A pymongo `MongoClient` object.
        """
        return MongoClient(self.replica_set_uri(), serverSelectionTimeoutMS=1000)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def check_server_info(self, client: MongoClient):
        """Repeatly checks to see if the server is ready, timing out after 10 tries.

        Args:
            client: MongoClient client to check for server info.
        Returns:
            client.server_info information about the server.
        """
        client = self.client()
        return client.server_info()

    def is_ready(self) -> bool:
        """Is the MongoDB server ready to services requests.

        Args:
            None
        Returns:
            bool: True if services is ready False otherwise.
        """
        ready = False
        client = self.client()
        try:
            self.check_server_info(client)
            ready = True
        except RetryError as e:
            logger.debug("mongod.service is not ready yet. %s", e)
        finally:
            client.close()
        return ready

    def initialize_replica_set(self, hosts: list) -> None:
        """Initialize the MongoDB replica set.

        Args:
            hosts: a list of peer host addresses.
        """
        config = {
            "_id": self._replica_set_name,
            "members": [{"_id": i, "host": h} for i, h in enumerate(hosts)],
        }
        logger.debug("setting up replica set with these options %s", config)
        client = self.client()
        try:
            client.admin.command("replSetInitiate", config)
        except ConnectionFailure as e:
            logger.error(
                "cannot initialize replica set: failure to connect to mongo client: error: %s",
                str(e),
            )
            raise e
        except ConfigurationError as e:
            logger.error("cannot initialize replica set: incorrect credentials: error: %s", str(e))
            raise e
        finally:
            client.close()

    def replica_set_uri(self, credentials=None) -> str:
        """Construct a replica set URI.

        Args:
            credentials: an optional dictionary with keys "username"
            and "password".

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
        for i, host in enumerate(self._unit_ips):
            if i:
                uri += ","
            uri += "{}:{}".format(host, self._port)
        uri += "/"
        logger.debug("uri %s", uri)
        return uri
