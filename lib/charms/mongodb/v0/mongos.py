"""Code for interactions with MongoDB."""
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from dataclasses import dataclass
from typing import Optional, Set
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.errors import PyMongoError

# The unique Charmhub library identifier, never change it
LIBID = "49c69d9977574dd7942eb7b54f43355b"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 7

# path to store mongodb ketFile
logger = logging.getLogger(__name__)


@dataclass
class MongosConfiguration:
    """Class for mongos configuration.

    — database: database name.
    — username: username.
    — password: password.
    — hosts: full list of hosts to connect to, needed for the URI.
    - port: integer for the port to connect to connect to mongodb.
    - tls_external: indicator for use of internal TLS connection.
    - tls_internal: indicator for use of external TLS connection.
    """

    database: Optional[str]
    username: str
    password: str
    hosts: Set[str]
    port: int
    roles: Set[str]
    tls_external: bool
    tls_internal: bool

    @property
    def uri(self):
        """Return URI concatenated from fields."""
        hosts = [f"{host}:{self.port}" for host in self.hosts]
        hosts = ",".join(hosts)
        # Auth DB should be specified while user connects to application DB.
        auth_source = ""
        if self.database != "admin":
            auth_source = "&authSource=admin"
        return (
            f"mongodb://{quote_plus(self.username)}:"
            f"{quote_plus(self.password)}@"
            f"{hosts}/{quote_plus(self.database)}?"
            f"{auth_source}"
        )


class NotReadyError(PyMongoError):
    """Raised when not all replica set members healthy or finished initial sync."""


class MongosConnection:
    """In this class we create connection object to Mongos.

    Real connection is created on the first call to Mongos.
    Delayed connectivity allows to firstly check database readiness
    and reuse the same connection for an actual query later in the code.

    Connection is automatically closed when object destroyed.
    Automatic close allows to have more clean code.

    Note that connection when used may lead to the following pymongo errors: ConfigurationError,
    ConfigurationError, OperationFailure. It is suggested that the following pattern be adopted
    when using MongoDBConnection:

    with MongoMongos(self._mongos_config) as mongo:
        try:
            mongo.<some operation from this class>
        except ConfigurationError, ConfigurationError, OperationFailure:
            <error handling as needed>
    """

    def __init__(self, config: MongosConfiguration, uri=None, direct=False):
        """A MongoDB client interface.

        Args:
            config: MongoDB Configuration object.
            uri: allow using custom MongoDB URI, needed for replSet init.
            direct: force a direct connection to a specific host, avoiding
                    reading replica set configuration and reconnection.
        """
        self.mongodb_config = config

        if uri is None:
            uri = config.uri

        self.client = MongoClient(
            uri,
            directConnection=direct,
            connect=False,
            serverSelectionTimeoutMS=1000,
            connectTimeoutMS=2000,
        )
        return

    def __enter__(self):
        """Return a reference to the new connection."""
        return self

    def __exit__(self, object_type, value, traceback):
        """Disconnect from MongoDB client."""
        self.client.close()
        self.client = None

    def get_shard_members(self) -> Set[str]:
        """Gets shard members.

        Returns:
            A set of the shard members as reported by mongos.

        Raises:
            ConfigurationError, ConfigurationError, OperationFailure
        """
        shard_list = self.client.admin.command("listShards")
        curr_members = [
            self._hostname_from_hostport(member["host"]) for member in shard_list["shards"]
        ]
        return set(curr_members)

    def add_shard(self, shard_name, shard_hosts, shard_port=27017):
        """Adds shard to the cluster.

        Raises:
            ConfigurationError, ConfigurationError, OperationFailure
        """
        shard_hosts = [f"{host}:{shard_port}" for host in shard_hosts]
        shard_hosts = ",".join(shard_hosts)
        shard_url = f"{shard_name}/{shard_hosts}"
        # TODO Future PR raise error when number of shards currently adding are higher than the
        # number of secondaries on the primary shard

        if shard_name in self.get_shard_members():
            logger.info("Skipping adding shard %s, shard is already in cluster", shard_name)
            return

        logger.info("Adding shard %s", shard_name)
        self.client.admin.command("addShard", shard_url)

    @staticmethod
    def _hostname_from_hostport(hostname: str) -> str:
        """Return hostname part from MongoDB returned.

        mongos typically returns a value that contains both, hostname, hosts, and ports.
        e.g. input: shard03/host7:27018,host8:27018,host9:27018
        Return shard name
        e.g. output: shard03
        """
        return hostname.split("/")[0]
