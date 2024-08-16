"""Code for interactions with MongoDB."""

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import abc
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Set

from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError
from tenacity import RetryError, Retrying, stop_after_delay, wait_fixed

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


class NotReadyError(PyMongoError):
    """Raised when not all replica set members healthy or finished initial sync."""


# The unique Charmhub library identifier, never change it
LIBID = "3037662a76cc4bf1876d4659c88e77e5"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

# path to store mongodb ketFile
logger = logging.getLogger(__name__)


@dataclass
class MongoConfiguration:
    """Class for Mongo configurations usable my mongos and mongodb.

    — replset: name of replica set
    - port: connection port
    — database: database name.
    — username: username.
    — password: password.
    — hosts: full list of hosts to connect to, needed for the URI.
    - tls_external: indicator for use of internal TLS connection.
    - tls_internal: indicator for use of external TLS connection.
    """

    database: Optional[str]
    username: str
    password: str
    hosts: Set[str]
    roles: Set[str]
    tls_external: bool
    tls_internal: bool

    @property
    @abc.abstractmethod
    def uri(self):
        """Return URI concatenated from fields."""


class MongoConnection:
    """In this class we create connection object to Mongo[s/db].

    This class is meant for agnositc functions in mongos and mongodb.

    Real connection is created on the first call to Mongo[s/db].
    Delayed connectivity allows to firstly check database readiness
    and reuse the same connection for an actual query later in the code.

    Connection is automatically closed when object destroyed.
    Automatic close allows to have more clean code.

    Note that connection when used may lead to the following pymongo errors: ConfigurationError,
    ConfigurationError, OperationFailure. It is suggested that the following pattern be adopted
    when using MongoDBConnection:

    with MongoMongos(MongoConfig) as mongo:
        try:
            mongo.<some operation from this class>
        except ConfigurationError, OperationFailure:
            <error handling as needed>
    """

    def __init__(self, config: MongoConfiguration, uri=None, direct=False):
        """A MongoDB client interface.

        Args:
            config: MongoDB Configuration object.
            uri: allow using custom MongoDB URI, needed for replSet init.
            direct: force a direct connection to a specific host, avoiding
                    reading replica set configuration and reconnection.
        """
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

    @property
    def is_ready(self) -> bool:
        """Is the MongoDB server ready for services requests.

        Returns:
            True if services is ready False otherwise. Retries over a period of 60 seconds times to
            allow server time to start up.

        Raises:
            ConfigurationError, ConfigurationError, OperationFailure
        """
        try:
            for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
                with attempt:
                    # The ping command is cheap and does not require auth.
                    self.client.admin.command("ping")
        except RetryError:
            return False

        return True

    def create_user(self, config: MongoConfiguration):
        """Create user.

        Grant read and write privileges for specified database.
        """
        self.client.admin.command(
            "createUser",
            config.username,
            pwd=config.password,
            roles=self._get_roles(config),
            mechanisms=["SCRAM-SHA-256"],
        )

    def update_user(self, config: MongoConfiguration):
        """Update grants on database."""
        self.client.admin.command(
            "updateUser",
            config.username,
            roles=self._get_roles(config),
        )

    def set_user_password(self, username, password: str):
        """Update the password."""
        self.client.admin.command(
            "updateUser",
            username,
            pwd=password,
        )

    def create_role(self, role_name: str, privileges: dict, roles: dict = []):
        """Creates a new role.

        Args:
            role_name: name of the role to be added.
            privileges: privileges to be associated with the role.
            roles: List of roles from which this role inherits privileges.
        """
        try:
            self.client.admin.command(
                "createRole", role_name, privileges=[privileges], roles=roles
            )
        except OperationFailure as e:
            if not e.code == 51002:  # Role already exists
                logger.error("Cannot add role. error=%r", e)
                raise e

    @staticmethod
    def _get_roles(config: MongoConfiguration) -> List[dict]:
        """Generate roles List."""
        supported_roles = {
            "admin": [
                {"role": "userAdminAnyDatabase", "db": "admin"},
                {"role": "readWriteAnyDatabase", "db": "admin"},
                {"role": "userAdmin", "db": "admin"},
            ],
            "monitor": [
                {"role": "explainRole", "db": "admin"},
                {"role": "clusterMonitor", "db": "admin"},
                {"role": "read", "db": "local"},
            ],
            "backup": [
                {"db": "admin", "role": "readWrite", "collection": ""},
                {"db": "admin", "role": "backup"},
                {"db": "admin", "role": "clusterMonitor"},
                {"db": "admin", "role": "restore"},
                {"db": "admin", "role": "pbmAnyAction"},
            ],
            "default": [
                {"role": "readWrite", "db": config.database},
            ],
        }
        return [role_dict for role in config.roles for role_dict in supported_roles[role]]

    def drop_user(self, username: str):
        """Drop user."""
        self.client.admin.command("dropUser", username)

    def get_users(self) -> Set[str]:
        """Add a new member to replica set config inside MongoDB."""
        users_info = self.client.admin.command("usersInfo")
        return set(
            [
                user_obj["user"]
                for user_obj in users_info["users"]
                if re.match(r"^relation-\d+$", user_obj["user"])
            ]
        )

    def get_databases(self) -> Set[str]:
        """Return list of all non-default databases."""
        system_dbs = ("admin", "local", "config")
        databases = self.client.list_database_names()
        return set([db for db in databases if db not in system_dbs])

    def drop_database(self, database: str):
        """Drop a non-default database."""
        system_dbs = ("admin", "local", "config")
        if database in system_dbs:
            return
        self.client.drop_database(database)
