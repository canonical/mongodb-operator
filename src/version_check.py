# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Class used to determine if a relevant version attribute across related applications are valid.

There are many potential applications for this. Here are a few examples:
1. in a sharded cluster where is is important that the shards and cluster manager have the same
components.
2. kafka connect and kafka broker apps working together and needing to have the same ubnderlying
version.

How to use:

1. in src/charm.py of requirer + provider
    in constructor [REQUIRED]:
    self.version_checker = self.CrossAppVersionChecker(
        self,
        version=x, # can be a revision of a charm, version of a snap, version of a workload, etc
        relations_to_check=[x,y,z],
        # only use if the version doesn't not need to exactly match our current version
        version_validity_range={"x": "<a,>b"})

    in update status hook [OPTIONAL]:
    if not self.version_checker.are_related_apps_valid():
        logger.debug(
            "Warning relational version check failed, these relations have mismatched versions",
            "%s",
            self.version_checker(self.version_checker.get_invalid_versions())
        )
        # can set status, instruct user to change

2. other areas of the charm (i.e. joined events, action events, etc) [OPTIONAL]:
    if not self.charm.version_checker.are_related_apps_valid():
        # do something - i.e. fail event or log message

3. in upgrade handler of requirer + provider [REQUIRED]:
    if [last unit to upgrade]:
        self.charm.version.set_version_across_all_relations()


"""
import logging
from typing import Dict, List, Optional, Tuple

from ops.charm import CharmBase
from ops.framework import Object
from ops.model import Unit

logger = logging.getLogger(__name__)

VERSION_CONST = "version"
DEPLOYMENT_TYPE = "deployment"
PREFIX_DIR = "/var/lib/juju/agents/"
LOCAL_BUILT_CHARM_PREFIX = "local"


def get_charm_revision(unit: Unit) -> int:
    """Returns the charm revision.

    TODO: Keep this until ops framework supports: https://github.com/canonical/operator/issues/1255
    """
    file_path = f"{PREFIX_DIR}unit-{unit.name.replace('/','-')}/charm/.juju-charm"
    with open(file_path) as f:
        charm_path = f.read().rstrip()

    # revision of charm in a locally built chamr is unreliable:
    # https://chat.canonical.com/canonical/pl/ro9935ayxbyyxn9hn6opy4f4xw
    if charm_path.split(":")[0] == LOCAL_BUILT_CHARM_PREFIX:
        logger.debug("Charm is locally built. Cannot determine revision number.")
        return 0

    # charm_path is of the format ch:amd64/jammy/<charm-name>-<revision number>
    revision = charm_path.split("-")[-1]
    return int(revision)


class CrossAppVersionChecker(Object):
    """Verifies versions across multiple integrated applications."""

    def __init__(
        self,
        charm: CharmBase,
        version: int,
        relations_to_check: List[str],
        version_validity_range: Optional[Dict] = None,
    ) -> None:
        """Constructor for CrossAppVersionChecker.

        Args:
            charm: charm to inherit from
            version: (int), the current version of the desired attribute of the charm
            relations_to_check: (List), a list of relations who should have compatible versions
                with the current charm
            version_validity_range: (Optional Dict), a list of ranges for valid version ranges.
                If not provided it is assumed that relations on the provided interface must have
                the same version.
        """
        super().__init__(charm, None)
        self.charm = charm
        # Future PR: upgrade this to a dictionary name versions
        self.version = version
        self.relations_to_check = relations_to_check

        for rel in relations_to_check:
            self.framework.observe(
                charm.on[rel].relation_created,
                self.set_version_on_relation_created,
            )

        # this feature has yet to be implemented, MongoDB does not need it and it is unclear if
        # this will be extended to other charms. If this code is extended to other charms and
        # there is a valid usecase we will use the `version_validity_range` variable in the
        # function `get_invalid_versions`
        self.version_validity_range = version_validity_range

    def get_invalid_versions(self) -> List[Tuple[str, int]]:
        """Returns a list of (app name, version number) pairs, if the version number mismatches.

        Mismatches are decided based on version_validity_range, if version_validity_range is not
        provided, then the mismatch is expected to match this current app's version number.

        Raises:
            NoVersionError.
        """
        try:
            invalid_relations = []
            for relation_name in self.relations_to_check:
                for relation in self.charm.model.relations[relation_name]:
                    related_version = relation.data[relation.app][VERSION_CONST]
                    if int(related_version) != self.version:
                        invalid_relations.append((relation.app.name, int(related_version)))
        except KeyError:
            raise NoVersionError(f"Expected {relation.app.name} to have version info.")

        return invalid_relations

    def get_version_of_related_app(self, related_app_name: str) -> int:
        """Returns a int for the version of the related app.

        Raises:
            NoVersionError.
        """
        try:
            for relation_name in self.relations_to_check:
                for rel in self.charm.model.relations[relation_name]:
                    if rel.app.name == related_app_name:
                        return int(rel.data[rel.app][VERSION_CONST])
        except KeyError:
            pass

        raise NoVersionError(f"Expected {related_app_name} to have version info.")

    def get_deployment_prefix(self) -> str:
        """Returns the deployment prefix, indicating if the charm is locally deployred or not.

        TODO: Keep this until ops framework supports:
            https://github.com/canonical/operator/issues/1255
        """
        file_path = f"{PREFIX_DIR}/unit-{self.charm.unit.name.replace('/','-')}/charm/.juju-charm"
        with open(file_path) as f:
            charm_path = f.read().rstrip()

        return charm_path.split(":")[0]

    def are_related_apps_valid(self) -> bool:
        """Returns True if a related app has a version that's incompatible with the current app.

        Raises:
            NoVersionError.
        """
        return self.get_invalid_versions() == []

    def set_version_across_all_relations(self) -> None:
        """Sets the version number across all related apps, prvided by relations_to_check."""
        if not self.charm.unit.is_leader():
            return

        for relation_name in self.relations_to_check:
            for rel in self.charm.model.relations[relation_name]:
                rel.data[self.charm.model.app][VERSION_CONST] = str(self.version)
                rel.data[self.charm.model.app][DEPLOYMENT_TYPE] = str(self.get_deployment_prefix())

    def set_version_on_related_app(self, relation_name: str, related_app_name: str) -> None:
        """Sets the version number across for a specified relation on a specified app."""
        if not self.charm.unit.is_leader():
            return

        for rel in self.charm.model.relations[relation_name]:
            if rel.app.name == related_app_name:
                rel.data[self.charm.model.app][VERSION_CONST] = str(self.version)
                rel.data[self.charm.model.app][DEPLOYMENT_TYPE] = str(self.get_deployment_prefix())

    def set_version_on_relation_created(self, event) -> None:
        """Shares the charm's revision to the newly integrated application.

        Raises:
            RelationInvalidError
        """
        if event.relation.name not in self.relations_to_check:
            raise RelationInvalidError(
                f"Provided relation: {event.relation.name} not in self.relations_to_check."
            )

        self.set_version_on_related_app(event.relation.name, event.app.name)

    def is_integrated_to_locally_built_charm(self) -> bool:
        """Returns a boolean value indicating whether the charm is integrated is a local charm.

        NOTE: this function ONLY checks relations on the provided interfaces in
        relations_to_check.
        """
        for relation_name in self.relations_to_check:
            for rel in self.charm.model.relations[relation_name]:
                if rel.data[rel.app][DEPLOYMENT_TYPE] == LOCAL_BUILT_CHARM_PREFIX:
                    return True

        return False

    def is_local_charm(self, app_name: str) -> bool:
        """Returns a boolean value indicating whether the provided app is a local charm."""
        if self.charm.app.name == app_name:
            return self.get_deployment_prefix() == LOCAL_BUILT_CHARM_PREFIX

        try:
            for relation_name in self.relations_to_check:
                for rel in self.charm.model.relations[relation_name]:
                    if rel.app.name == app_name:
                        return rel.data[rel.app][DEPLOYMENT_TYPE] == LOCAL_BUILT_CHARM_PREFIX
        except KeyError:
            pass

        raise NoVersionError(f"Expected {app_name} to have version info.")


class CrossAppVersionCheckerError(Exception):
    """Parent class for errors raised in CrossAppVersionChecker class."""


class RelationInvalidError(CrossAppVersionCheckerError):
    """Raised if a relation is not in the provided set of relations to check."""


class NoVersionError(CrossAppVersionCheckerError):
    """Raised if an application does not contain any version information."""
