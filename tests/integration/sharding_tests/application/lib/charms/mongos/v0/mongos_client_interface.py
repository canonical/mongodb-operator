# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""In this class, we manage relations between config-servers and shards.

This class handles the sharing of secrets between sharded components, adding shards, and removing
shards.
"""
import logging

from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseProvides,
    DatabaseRequires,
)
from ops.charm import CharmBase
from ops.framework import Object

logger = logging.getLogger(__name__)
DATABASE_KEY = "database"
USER_ROLES_KEY = "extra-user-roles"
MONGOS_RELATION_NAME = "mongos_proxy"

# TODO - the below LIBID, LIBAPI, and LIBPATCH are not valid and were made manually. These will be
# created automatically once the charm has been published. The charm has not yet been published
# due to:
# https://discourse.charmhub.io/t/request-ownership-of-reserved-mongos-charm/12735

# The unique Charmhub library identifier, never change it
LIBID = "58ad1ccca4974932ba22b97781b9b2a0"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

"""Library to manage the relation for the application between mongos and the deployed application.
In short, this relation ensure that:
1. mongos receives the specified database and users roles needed by the host application
2. the host application receives the generated username, password and uri for connecting to the 
sharded cluster.

This library contains the Requires and Provides classes for handling the relation between an
application and mongos. The mongos application relies on the MongosProvider class and the deployed
application uses the MongoDBRequires class.

The following is an example of how to use the MongoDBRequires class to specify the roles and 
database name:

```python
from charms.mongos.v0.mongos_client_interface import MongosRequirer


class ApplicationCharm(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)

        # relation events for mongos client
        self._mongos_client = MongosRequirer(
            self,
            database_name="my-test-db",
            extra_user_roles="admin",
        )
```

To receive the username, password, and uri:
# TODO this is to be implemented in a future PR
"""


class MongosProvider(Object):
    """Manage relations between the mongos router and the application on the mongos side."""

    def __init__(self, charm: CharmBase, relation_name: str = MONGOS_RELATION_NAME) -> None:
        """Constructor for MongosProvider object."""
        self.relation_name = relation_name
        self.charm = charm
        self.database_provides = DatabaseProvides(self.charm, relation_name=self.relation_name)

        super().__init__(charm, self.relation_name)
        self.framework.observe(
            charm.on[self.relation_name].relation_changed, self._on_relation_changed
        )

        # TODO Future PRs handle relation broken

    def _on_relation_changed(self, event) -> None:
        """Handles updating the database and extra user roles."""
        if not self.charm.unit.is_leader():
            return

        relation_data = event.relation.data[event.app]
        new_database_name = relation_data.get(DATABASE_KEY, self.charm.database)
        new_extra_user_roles = relation_data.get(USER_ROLES_KEY, self.charm.extra_user_roles)

        if new_database_name != self.charm.database:
            self.charm.set_database(new_database_name)

        if new_extra_user_roles != self.charm.extra_user_roles:
            if isinstance(new_extra_user_roles, str):
                new_extra_user_roles = [new_extra_user_roles]

            self.charm.set_user_roles(new_extra_user_roles)


class MongosRequirer(Object):
    """Manage relations between the mongos router and the application on the application side."""

    def __init__(
        self,
        charm: CharmBase,
        database_name: str,
        extra_user_roles: str,
        relation_name: str = MONGOS_RELATION_NAME,
    ) -> None:
        """Constructor for MongosRequirer object."""
        self.relation_name = relation_name
        self.charm = charm

        if not database_name:
            database_name = f"{self.charm.app}"

        self.database_requires = DatabaseRequires(
            self.charm,
            relation_name=self.relation_name,
            database_name=database_name,
            extra_user_roles=extra_user_roles,
        )

        super().__init__(charm, self.relation_name)
        # TODO Future PRs handle relation broken
