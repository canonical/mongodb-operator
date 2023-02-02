#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# SPDX-License-Identifier: Apache-2.0
"""A charm of the s3 integrator service."""

import base64
import json
import logging
import re
from typing import Dict, List, Optional

import ops
import ops.charm
import ops.framework
import ops.lib
import ops.main
import ops.model
from charms.data_platform_libs.v0.s3 import CredentialRequestedEvent, S3Provider
from constants import PEER, S3_LIST_OPTIONS, S3_MANDATORY_OPTIONS, S3_OPTIONS
from ops.charm import ActionEvent, ConfigChangedEvent, RelationChangedEvent, StartEvent
from ops.model import ActiveStatus, BlockedStatus

logger = logging.getLogger(__name__)


class S3IntegratorCharm(ops.charm.CharmBase):
    """Charm for s3 integrator service."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.s3_provider = S3Provider(self, "s3-credentials")
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.s3_provider.on.credentials_requested, self._on_credential_requested
        )
        self.framework.observe(self.on[PEER].relation_changed, self._on_peer_relation_changed)
        # actions
        self.framework.observe(self.on.sync_s3_credentials_action, self._on_sync_s3_credentials)
        self.framework.observe(self.on.get_s3_credentials_action, self.on_get_credentials_action)
        self.framework.observe(
            self.on.get_s3_connection_info_action, self.on_get_connection_info_action
        )

    @property
    def app_peer_data(self) -> Dict:
        """Application peer relation data object."""
        relation = self.model.get_relation(PEER)
        if not relation:
            return {}

        return relation.data[self.app]

    @property
    def unit_peer_data(self) -> Dict:
        """Peer relation data object."""
        relation = self.model.get_relation(PEER)
        if relation is None:
            return {}

        return relation.data[self.unit]

    def _on_start(self, _: StartEvent) -> None:
        """Handle the charm startup event."""
        missing_options = self.get_missing_parameters()
        self.unit.status = ops.model.BlockedStatus(f"Missing parameters: {missing_options}")

    def _on_config_changed(self, _: ConfigChangedEvent) -> None:
        """Event handler for configuration changed events."""
        # Only execute in the unit leader
        if not self.unit.is_leader():
            return
        logger.debug(f"Current configuration: {self.config}")
        # store updates from config and apply them.
        update_config = {}

        # iterate over the option and check for updates
        for option in S3_OPTIONS:
            if option not in self.config:
                logger.warning(f"Option {option} is not valid option!")
                continue
            # skip in case of empty config
            if self.config[option] == "":
                # reset previous value if present (e.g., juju model-config --reset PARAMETER)
                if self.get_secret("app", option) is not None:
                    self.set_secret("app", option, None)
                # skip in case of default value
                continue
            # manage comma-separated items for attributes
            if option == "attributes":
                values = self.config[option].split(",")
                update_config.update({option: values})
                self.set_secret("app", option, json.dumps(values))
            # manage ca-chain
            elif option == "tls-ca-chain":
                ca_chain = self.parse_ca_chain(
                    base64.b64decode(self.config[option]).decode("utf-8")
                )
                update_config.update({option: ca_chain})
                self.set_secret("app", option, json.dumps(ca_chain))
            else:
                update_config.update({option: self.config[option]})
                self.set_secret("app", option, self.config[option])

        if len(self.s3_provider.relations) > 0:
            for relation in self.s3_provider.relations:
                self.s3_provider.update_connection_info(relation.id, update_config)

    def _on_credential_requested(self, event: CredentialRequestedEvent):
        """Handle the `credential-requested` event."""
        if not self.unit.is_leader():
            return
        relation_id = event.relation.id

        bucket = event.bucket
        logger.debug(f"Desired bucket name: {bucket}")
        assert bucket is not None
        # if bucket name is already specified ignore the one provided by the requirer app
        if self.get_secret("app", bucket) is None:
            self.set_secret("app", "bucket", bucket)

        desired_configuration = {}
        # collect all configuration options
        for option in S3_OPTIONS:
            if self.get_secret("app", option) is not None:
                if option in S3_LIST_OPTIONS:
                    # serialize lists options from json string
                    desired_configuration[option] = json.loads(self.get_secret("app", option))
                else:
                    desired_configuration[option] = self.get_secret("app", option)

        # update connection parameters in the relation data bug
        self.s3_provider.update_connection_info(relation_id, desired_configuration)

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
            self.unit_peer_data.update({key: value})
        elif scope == "app":
            if not value:
                del self.app_peer_data[key]
                return
            self.app_peer_data.update({key: value})
        else:
            raise RuntimeError("Unknown secret scope.")

    def get_missing_parameters(self) -> List[str]:
        """Returns the missing mandatory parameters that are not stored in the peer relation."""
        missing_options = []
        for config_option in S3_MANDATORY_OPTIONS:
            if not self.get_secret("app", config_option):
                missing_options.append(config_option)
        return missing_options

    def _on_sync_s3_credentials(self, event: ops.charm.ActionEvent) -> None:
        """Handle a user synchronizing their S3 credentials to the charm."""
        # only leader can write the new access and secret key into peer relation.
        if not self.unit.is_leader():
            event.fail("The action can be run only on leader unit.")
            return
        # read parameters from the event
        access_key = event.params["access-key"]
        secret_key = event.params["secret-key"]
        # set parameters in the secrets
        self.set_secret("app", "access-key", access_key)
        self.set_secret("app", "secret-key", secret_key)
        credentials = {"access-key": access_key, "secret-key": secret_key}
        # update relation data if the relation is present
        if len(self.s3_provider.relations) > 0:
            for relation in self.s3_provider.relations:
                self.s3_provider.set_access_key(relation.id, access_key)
                self.s3_provider.set_secret_key(relation.id, secret_key)
        event.set_results(credentials)

    def _on_peer_relation_changed(self, _: RelationChangedEvent) -> None:
        """Handle the peer relation changed event."""
        # Check if mandatory configuration options are present and change the status
        missing_options = self.get_missing_parameters()
        logger.info(f"Missing options: {missing_options}")
        if missing_options:
            self.unit.status = BlockedStatus(f"Missing parameters: {missing_options}")
            return
        self.unit.status = ActiveStatus()

    @property
    def _peers(self):
        """Retrieve the peer relation."""
        return self.model.get_relation(PEER)

    def on_get_credentials_action(self, event: ActionEvent):
        """Handle the action `get-credential`."""
        access_key = self.get_secret("app", "access-key")
        secret_key = self.get_secret("app", "secret-key")
        if access_key is None or secret_key is None:
            event.fail("Credentials are not set!")
            return
        credentials = {"access-key": access_key, "secret-key": secret_key}
        event.set_results(credentials)

    def on_get_connection_info_action(self, event: ActionEvent):
        """Handle the action `get connection info`."""
        current_configuration = {}
        for option in S3_OPTIONS:
            if self.get_secret("app", option) is not None:
                current_configuration[option] = self.get_secret("app", option)
        # emit event fail if no option is set in the charm
        if len(current_configuration) == 0:
            event.fail("Credentials are not set!")
            return
        event.set_results(current_configuration)

    @staticmethod
    def parse_ca_chain(ca_chain_pem: str) -> List[str]:
        """Returns list of certificates based on a PEM CA Chain file.

        Args:
            ca_chain_pem (str): String containing list of certificates.
            This string should look like:
                -----BEGIN CERTIFICATE-----
                <cert 1>
                -----END CERTIFICATE-----
                -----BEGIN CERTIFICATE-----
                <cert 2>
                -----END CERTIFICATE-----

        Returns:
            list: List of certificates
        """
        chain_list = re.findall(
            pattern="(?=-----BEGIN CERTIFICATE-----)(.*?)(?<=-----END CERTIFICATE-----)",
            string=ca_chain_pem,
            flags=re.DOTALL,
        )
        if not chain_list:
            raise ValueError("No certificate found in chain file")
        return chain_list


if __name__ == "__main__":
    ops.main.main(S3IntegratorCharm)
