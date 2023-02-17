# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from unittest import mock
from unittest.mock import patch

from ops.testing import Harness

from charm import MongodbOperatorCharm

from .helpers import patch_network_get

RELATION_NAME = "certificates"


class TestMongoTLS(unittest.TestCase):
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self):
        self.harness = Harness(MongodbOperatorCharm)
        self.harness.begin()
        self.harness.add_relation("database-peers", "database-peers")
        self.harness.set_leader(True)
        self.charm = self.harness.charm
        self.addCleanup(self.harness.cleanup)

    @patch_network_get(private_address="1.1.1.1")
    def test_set_internal_tls_private_key(self):
        """Tests setting of TLS private key via the leader, ie both internal and external.

        Note: this implicitly tests: _request_certificate & _parse_tls_file
        """
        # Tests for leader unit (ie internal certificates and external certificates)
        action_event = mock.Mock()
        action_event.params = {}

        # generated rsa key test - leader
        self.harness.charm.tls._on_set_tls_private_key(action_event)
        self.verify_internal_rsa_csr()
        self.verify_external_rsa_csr()

        with open("tests/unit/data/key.pem") as f:
            key_contents = f.readlines()
            key_contents = "".join(key_contents)

        set_app_rsa_key = key_contents
        # we expect the app rsa key to be parsed such that its trailing newline is removed.
        parsed_app_rsa_key = set_app_rsa_key[:-1]
        action_event.params = {"internal-key": set_app_rsa_key}
        self.harness.charm.tls._on_set_tls_private_key(action_event)
        self.verify_internal_rsa_csr(specific_rsa=True, expected_rsa=parsed_app_rsa_key)
        self.verify_external_rsa_csr()

    @patch_network_get(private_address="1.1.1.1")
    def test_set_external_tls_private_key(self):
        """Tests setting of TLS private key in external certificate scenarios.

        Note: this implicitly tests: _request_certificate & _parse_tls_file
        """
        #  Tests for non-leader unit (ie external certificates)
        self.harness.set_leader(False)
        action_event = mock.Mock()
        action_event.params = {}

        # generated rsa key test - non-leader
        self.harness.charm.tls._on_set_tls_private_key(action_event)
        self.verify_external_rsa_csr()
        # non-leaders should not reset the app key and app csr
        self.verify_internal_rsa_csr(
            specific_rsa=True, expected_rsa=None, specific_csr=True, expected_csr=None
        )

        # provided rsa key test - non-leader

        with open("tests/unit/data/key.pem") as f:
            key_contents = f.readlines()
            key_contents = "".join(key_contents)

        set_unit_rsa_key = key_contents
        # we expect the app rsa key to be parsed such that its trailing newline is removed.
        parsed_unit_rsa_key = set_unit_rsa_key[:-1]

        action_event.params = {"external-key": set_unit_rsa_key}
        self.harness.charm.tls._on_set_tls_private_key(action_event)
        self.verify_external_rsa_csr(specific_rsa=True, expected_rsa=parsed_unit_rsa_key)
        # non-leaders should not reset the app key and app csr
        self.verify_internal_rsa_csr(
            specific_rsa=True, expected_rsa=None, specific_csr=True, expected_csr=None
        )

    @patch_network_get(private_address="1.1.1.1")
    def test_tls_relation_joined_non_leader(self):
        """Test that non-leader units set only external certificates."""
        self.harness.set_leader(False)
        self.relate_to_tls_certificates_operator()
        # non leaders should not be allowed to set internal certificates
        self.verify_internal_rsa_csr(
            specific_rsa=True, expected_rsa=None, specific_csr=True, expected_csr=None
        )
        self.verify_external_rsa_csr()

    @patch_network_get(private_address="1.1.1.1")
    def test_tls_relation_joined_leader(self):
        """Test that leader units set both external and internal certificates."""
        self.relate_to_tls_certificates_operator()
        self.verify_internal_rsa_csr()
        self.verify_external_rsa_csr()

    @patch("charm.MongodbOperatorCharm.restart_mongod_service")
    @patch_network_get(private_address="1.1.1.1")
    def test_tls_relation_broken_non_leader(self, restart_mongod_service):
        """Test non-leader removes only external cert & chain."""
        # set initial certificate values
        rel_id = self.relate_to_tls_certificates_operator()
        app_rsa_key = self.harness.charm.app_peer_data["key"]
        app_csr = self.harness.charm.app_peer_data["csr"]

        self.harness.set_leader(False)
        self.harness.remove_relation(rel_id)
        self.assertIsNone(self.harness.charm.unit_peer_data.get("ca", None))
        self.assertIsNone(self.harness.charm.unit_peer_data.get("cert", None))
        self.assertIsNone(self.harness.charm.unit_peer_data.get("chain", None))

        #  internal certificate should be maintained
        self.verify_internal_rsa_csr(
            specific_rsa=True, expected_rsa=app_rsa_key, specific_csr=True, expected_csr=app_csr
        )

        # units should be restarted after updating TLS settings
        restart_mongod_service.assert_called()

    @patch("charm.MongodbOperatorCharm.restart_mongod_service")
    @patch_network_get(private_address="1.1.1.1")
    def test_tls_relation_broken_leader(self, restart_mongod_service):
        """Test leader removes both external and internal certificates."""
        # set initial certificate values
        rel_id = self.relate_to_tls_certificates_operator()

        self.harness.remove_relation(rel_id)

        # internal certificates and external certificates should be removed
        self.assertIsNone(self.harness.charm.unit_peer_data.get("ca", None))
        self.assertIsNone(self.harness.charm.unit_peer_data.get("cert", None))
        self.assertIsNone(self.harness.charm.unit_peer_data.get("chain", None))
        self.assertIsNone(self.harness.charm.app_peer_data.get("ca", None))
        self.assertIsNone(self.harness.charm.app_peer_data.get("cert", None))
        self.assertIsNone(self.harness.charm.app_peer_data.get("chain", None))

        # units should be restarted after updating TLS settings
        restart_mongod_service.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    def test_external_certificate_expiring(self):
        """Verifies that when an external certificate expires a csr is made."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.unit_peer_data["cert"] = "unit-cert"

        # simulate current certificate expiring
        old_csr = self.harness.charm.unit_peer_data["csr"]
        self.charm.tls.certs.on.certificate_expiring.emit(certificate="unit-cert", expiry=None)

        # verify a new csr was generated
        new_csr = self.harness.charm.unit_peer_data["csr"]
        self.assertNotEqual(old_csr, new_csr)

    @patch_network_get(private_address="1.1.1.1")
    def test_internal_certificate_expiring(self):
        """Verifies that when an internal certificate expires a csr is made."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.app_peer_data["cert"] = "app-cert"
        self.harness.charm.unit_peer_data["cert"] = "unit-cert"

        # simulate current certificate expiring on non-leader
        self.harness.set_leader(False)
        old_csr = self.harness.charm.app_peer_data["csr"]
        self.charm.tls.certs.on.certificate_expiring.emit(certificate="app-cert", expiry=None)

        # the csr should not be changed by non-leader units
        new_csr = self.harness.charm.app_peer_data["csr"]
        self.assertEqual(old_csr, new_csr)

        # verify a new csr was generated when leader receives expiry
        self.harness.set_leader(True)
        self.charm.tls.certs.on.certificate_expiring.emit(certificate="app-cert", expiry=None)
        new_csr = self.harness.charm.app_peer_data["csr"]
        self.assertNotEqual(old_csr, new_csr)

    @patch_network_get(private_address="1.1.1.1")
    def test_unknown_certificate_expiring(self):
        """Verifies that when an unknown certificate expires nothing happens."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.app_peer_data["cert"] = "app-cert"
        self.harness.charm.unit_peer_data["cert"] = "unit-cert"

        # simulate unknown certificate expiring on leader
        old_app_csr = self.harness.charm.app_peer_data["csr"]
        old_unit_csr = self.harness.charm.unit_peer_data["csr"]
        self.charm.tls.certs.on.certificate_expiring.emit(certificate="unknown-cert", expiry=None)
        new_app_csr = self.harness.charm.app_peer_data["csr"]
        new_unit_csr = self.harness.charm.unit_peer_data["csr"]
        self.assertEqual(old_app_csr, new_app_csr)
        self.assertEqual(old_unit_csr, new_unit_csr)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._push_tls_certificate_to_workload")
    @patch("charm.MongodbOperatorCharm.restart_mongod_service")
    def test_external_certificate_available(self, restart_mongod_service, _):
        """Tests behavior when external certificate is made available."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.unit_peer_data["csr"] = "unit-crs"
        self.harness.charm.unit_peer_data["cert"] = "unit-cert-old"
        self.harness.charm.app_peer_data["cert"] = "app-cert"

        self.charm.tls.certs.on.certificate_available.emit(
            certificate_signing_request="unit-crs",
            chain=["unit-chain"],
            certificate="unit-cert",
            ca="unit-ca",
        )

        self.assertEqual(self.harness.charm.unit_peer_data["chain"], "unit-chain")
        self.assertEqual(self.harness.charm.unit_peer_data["cert"], "unit-cert")
        self.assertEqual(self.harness.charm.unit_peer_data["ca"], "unit-ca")

        restart_mongod_service.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._push_tls_certificate_to_workload")
    @patch("charm.MongodbOperatorCharm.restart_mongod_service")
    def test_internal_certificate_available(self, restart_mongod_service, _):
        """Tests behavior when internal certificate is made available."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.app_peer_data["csr"] = "app-crs"
        self.harness.charm.app_peer_data["cert"] = "app-cert-old"
        self.harness.charm.unit_peer_data["cert"] = "unit-cert"

        self.charm.tls.certs.on.certificate_available.emit(
            certificate_signing_request="app-crs",
            chain=["app-chain"],
            certificate="app-cert",
            ca="app-ca",
        )

        self.assertEqual(self.harness.charm.app_peer_data["chain"], "app-chain")
        self.assertEqual(self.harness.charm.app_peer_data["cert"], "app-cert")
        self.assertEqual(self.harness.charm.app_peer_data["ca"], "app-ca")

        restart_mongod_service.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm._push_tls_certificate_to_workload")
    @patch("charm.MongodbOperatorCharm.restart_mongod_service")
    def test_unknown_certificate_available(self, restart_mongod_service, _):
        """Tests that when an unknown certificate is available, nothing is updated."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.app_peer_data["chain"] = "app-chain-old"
        self.harness.charm.app_peer_data["cert"] = "app-cert-old"
        self.harness.charm.app_peer_data["csr"] = "app-crs-old"
        self.harness.charm.app_peer_data["ca"] = "app-ca-old"
        self.harness.charm.unit_peer_data["cert"] = "unit-cert"

        self.charm.tls.certs.on.certificate_available.emit(
            certificate_signing_request="app-crs",
            chain=["app-chain"],
            certificate="app-cert",
            ca="app-ca",
        )

        self.assertEqual(self.harness.charm.app_peer_data["chain"], "app-chain-old")
        self.assertEqual(self.harness.charm.app_peer_data["cert"], "app-cert-old")
        self.assertEqual(self.harness.charm.app_peer_data["ca"], "app-ca-old")

        restart_mongod_service.assert_not_called()

    # Helper functions
    def relate_to_tls_certificates_operator(self) -> int:
        """Relates the charm to the TLS certificates operator."""
        rel_id = self.harness.add_relation(RELATION_NAME, "tls-certificates-operator")
        self.harness.add_relation_unit(rel_id, "tls-certificates-operator/0")
        return rel_id

    def verify_external_rsa_csr(
        self, specific_rsa=False, expected_rsa=None, specific_csr=False, expected_csr=None
    ):
        """Verifies values of external rsa and csr.

        Checks if rsa/csr were randomly generated or if they are a provided value.
        """
        unit_rsa_key = self.harness.charm.unit_peer_data.get("key", None)
        unit_csr = self.harness.charm.unit_peer_data.get("csr", None)
        if specific_rsa:
            self.assertEqual(unit_rsa_key, expected_rsa)
        else:
            self.assertEqual(unit_rsa_key.split("\n")[0], "-----BEGIN RSA PRIVATE KEY-----")

        if specific_csr:
            self.assertEqual(unit_csr, expected_csr)
        else:
            self.assertEqual(unit_csr.split("\n")[0], "-----BEGIN CERTIFICATE REQUEST-----")

    def verify_internal_rsa_csr(
        self, specific_rsa=False, expected_rsa=None, specific_csr=False, expected_csr=None
    ):
        """Verifies values of internal rsa and csr.

        Checks if rsa/csr were randomly generated or if they are a provided value.
        """
        app_rsa_key = self.harness.charm.app_peer_data.get("key", None)
        app_csr = self.harness.charm.app_peer_data.get("csr", None)
        if specific_rsa:
            self.assertEqual(app_rsa_key, expected_rsa)
        else:
            self.assertEqual(app_rsa_key.split("\n")[0], "-----BEGIN RSA PRIVATE KEY-----")

        if specific_csr:
            self.assertEqual(app_csr, expected_csr)
        else:
            self.assertEqual(app_csr.split("\n")[0], "-----BEGIN CERTIFICATE REQUEST-----")
