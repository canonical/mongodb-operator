# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import subprocess
import unittest
from unittest import mock
from unittest.mock import patch

from ops.testing import Harness
from parameterized import parameterized

from charm import MongodbOperatorCharm

from .helpers import patch_network_get

RELATION_NAME = "certificates"


class TestMongoTLS(unittest.TestCase):
    @patch("charm.get_charm_revision")
    @patch_network_get(private_address="1.1.1.1")
    def setUp(self, *unused):
        self.harness = Harness(MongodbOperatorCharm)
        self.harness.begin()
        self.harness.add_relation("database-peers", "database-peers")
        self.harness.charm.app_peer_data["db_initialised"] = "True"
        self.harness.set_leader(True)
        self.charm = self.harness.charm
        self.addCleanup(self.harness.cleanup)

    @parameterized.expand([True, False])
    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongoDBTLS.get_new_sans")
    def test_set_tls_private_keys(self, leader, get_new_sans):
        """Tests setting of TLS private key via the leader, ie both internal and external.

        Note: this implicitly tests: _request_certificate & _parse_tls_file
        """
        self.harness.add_relation("certificates", "certificates")
        # Tests for leader unit (ie internal certificates and external certificates)
        get_new_sans.return_value = {"sans_dns": [""], "sans_ips": ["1.1.1.1"]}
        self.harness.set_leader(leader)
        action_event = mock.Mock()
        action_event.params = {}

        # generated rsa key test - leader
        self.harness.charm.tls._on_set_tls_private_key(action_event)
        self.verify_internal_rsa_csr()  # this one
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

    @parameterized.expand([True, False])
    @patch_network_get(private_address="1.1.1.1")
    def test_tls_relation_joined(self, leader):
        """Test that leader units set both external and internal certificates."""
        self.harness.set_leader(leader)
        self.relate_to_tls_certificates_operator()
        self.verify_internal_rsa_csr()
        self.verify_external_rsa_csr()

    @parameterized.expand([True, False])
    @patch("charm.MongodbOperatorCharm.restart_charm_services")
    @patch_network_get(private_address="1.1.1.1")
    def test_tls_relation_broken(self, leader, restart_charm_services):
        """Test removes both external and internal certificates."""
        self.harness.set_leader(leader)
        # set initial certificate values
        rel_id = self.relate_to_tls_certificates_operator()

        self.harness.remove_relation(rel_id)

        # internal certificates and external certificates should be removed
        for scope in ["unit", "app"]:
            ca_secret = self.harness.charm.get_secret(scope, "ca-secret")
            cert_secret = self.harness.charm.get_secret(scope, "cert-secret")
            chain_secret = self.harness.charm.get_secret(scope, "chain-secret")
            self.assertIsNone(ca_secret)
            self.assertIsNone(cert_secret)
            self.assertIsNone(chain_secret)

        # units should be restarted after updating TLS settings
        restart_charm_services.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    def test_external_certificate_expiring(self):
        """Verifies that when an external certificate expires a csr is made."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.set_secret("unit", "int-cert-secret", "int-cert")
        self.harness.charm.set_secret("unit", "ext-cert-secret", "ext-cert")

        # simulate current certificate expiring
        old_csr = self.harness.charm.get_secret("unit", "ext-csr-secret")

        self.charm.tls.certs.on.certificate_expiring.emit(certificate="ext-cert", expiry=None)

        # verify a new csr was generated

        new_csr = self.harness.charm.get_secret("unit", "ext-csr-secret")
        self.assertNotEqual(old_csr, new_csr)

    @patch_network_get(private_address="1.1.1.1")
    def test_internal_certificate_expiring(self):
        """Verifies that when an internal certificate expires a csr is made."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.set_secret("unit", "int-cert-secret", "int-cert")
        self.harness.charm.set_secret("unit", "ext-cert-secret", "ext-cert")

        # verify a new csr was generated when unit receives expiry
        old_csr = self.harness.charm.get_secret("unit", "int-csr-secret")
        self.charm.tls.certs.on.certificate_expiring.emit(certificate="int-cert", expiry=None)
        new_csr = self.harness.charm.get_secret("unit", "int-csr-secret")
        self.assertNotEqual(old_csr, new_csr)

    @patch_network_get(private_address="1.1.1.1")
    def test_unknown_certificate_expiring(self):
        """Verifies that when an unknown certificate expires nothing happens."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.set_secret("unit", "int-cert-secret", "ext-cert")
        self.harness.charm.set_secret("unit", "ext-cert-secret", "int-cert")

        # simulate unknown certificate expiring on leader
        old_app_csr = self.harness.charm.get_secret("unit", "int-csr-secret")
        old_unit_csr = self.harness.charm.get_secret("unit", "ext-csr-secret")

        self.charm.tls.certs.on.certificate_expiring.emit(certificate="unknown-cert", expiry="")

        new_app_csr = self.harness.charm.get_secret("unit", "int-csr-secret")
        new_unit_csr = self.harness.charm.get_secret("unit", "ext-csr-secret")

        self.assertEqual(old_app_csr, new_app_csr)
        self.assertEqual(old_unit_csr, new_unit_csr)

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm.push_tls_certificate_to_workload")
    @patch("charm.MongodbOperatorCharm.restart_charm_services")
    def test_external_certificate_available(self, restart_charm_services, _):
        """Tests behavior when external certificate is made available."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.set_secret("unit", "ext-csr-secret", "csr-secret")
        self.harness.charm.set_secret("unit", "ext-cert-secret", "unit-cert-old")
        self.harness.charm.set_secret("unit", "int-cert-secret", "app-cert")

        self.charm.tls.certs.on.certificate_available.emit(
            certificate_signing_request="csr-secret",
            chain=["unit-chain"],
            certificate="unit-cert",
            ca="unit-ca",
        )

        chain_secret = self.harness.charm.get_secret("unit", "ext-chain-secret")
        unit_secret = self.harness.charm.get_secret("unit", "ext-cert-secret")
        ca_secret = self.harness.charm.get_secret("unit", "ext-ca-secret")

        self.assertEqual(chain_secret, "unit-chain")
        self.assertEqual(unit_secret, "unit-cert")
        self.assertEqual(ca_secret, "unit-ca")

        restart_charm_services.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm.push_tls_certificate_to_workload")
    @patch("charm.MongodbOperatorCharm.restart_charm_services")
    def test_internal_certificate_available(self, restart_charm_services, _):
        """Tests behavior when internal certificate is made available."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.set_secret("unit", "int-csr-secret", "int-crs")
        self.harness.charm.set_secret("unit", "int-cert-secret", "int-cert-old")
        self.harness.charm.set_secret("unit", "ext-cert-secret", "ext-cert")

        self.charm.tls.certs.on.certificate_available.emit(
            certificate_signing_request="int-crs",
            chain=["int-chain"],
            certificate="int-cert",
            ca="int-ca",
        )

        chain_secret = self.harness.charm.get_secret("unit", "int-chain-secret")
        unit_secret = self.harness.charm.get_secret("unit", "int-cert-secret")
        ca_secret = self.harness.charm.get_secret("unit", "int-ca-secret")

        self.assertEqual(chain_secret, "int-chain")
        self.assertEqual(unit_secret, "int-cert")
        self.assertEqual(ca_secret, "int-ca")

        restart_charm_services.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm.push_tls_certificate_to_workload")
    @patch("charm.MongodbOperatorCharm.restart_charm_services")
    def test_unknown_certificate_available(self, restart_charm_services, _):
        """Tests that when an unknown certificate is available, nothing is updated."""
        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.set_secret("unit", "int-chain-secret", "app-chain-old")
        self.harness.charm.set_secret("unit", "int-cert-secret", "app-cert-old")
        self.harness.charm.set_secret("unit", "int-csr-secret", "app-crs-old")
        self.harness.charm.set_secret("unit", "int-ca-secret", "app-ca-old")
        self.harness.charm.set_secret("unit", "ext-cert-secret", "unit-cert")

        self.charm.tls.certs.on.certificate_available.emit(
            certificate_signing_request="app-crs",
            chain=["app-chain"],
            certificate="app-cert",
            ca="app-ca",
        )

        chain_secret = self.harness.charm.get_secret("unit", "int-chain-secret")
        unit_secret = self.harness.charm.get_secret("unit", "int-cert-secret")
        ca_secret = self.harness.charm.get_secret("unit", "int-ca-secret")

        self.assertEqual(chain_secret, "app-chain-old")
        self.assertEqual(unit_secret, "app-cert-old")
        self.assertEqual(ca_secret, "app-ca-old")

        restart_charm_services.assert_not_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm.push_tls_certificate_to_workload")
    @patch("ops.framework.EventBase.defer")
    def test_external_certificate_available_deferred(self, defer, _):
        """Tests behavior when external certificate is made available."""
        del self.harness.charm.app_peer_data["db_initialised"]

        # assume relation exists with a current certificate
        self.relate_to_tls_certificates_operator()
        self.harness.charm.set_secret("unit", "ext-csr-secret", "csr-secret")
        self.harness.charm.set_secret("unit", "ext-cert-secret", "unit-cert-old")
        self.harness.charm.set_secret("unit", "int-cert-secret", "app-cert")

        self.charm.tls.certs.on.certificate_available.emit(
            certificate_signing_request="csr-secret",
            chain=["unit-chain"],
            certificate="unit-cert",
            ca="unit-ca",
        )
        defer.assert_called()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.MongodbOperatorCharm.push_tls_certificate_to_workload")
    @patch("ops.framework.EventBase.defer")
    def test_external_certificate_broken_deferred(self, defer, _):
        """Tests behavior when external certificate is made available."""
        del self.harness.charm.app_peer_data["db_initialised"]

        # assume relation exists with a current certificate
        rel_id = self.relate_to_tls_certificates_operator()
        self.harness.remove_relation(rel_id)

        defer.assert_called()

    def test_get_new_sans_gives_node_port_for_mongos_k8s(self):
        """Tests that get_new_sans only gets node port for external mongos K8s."""
        mock_get_ext_mongos_host = mock.Mock()
        mock_get_ext_mongos_host.return_value = "node_port"
        self.harness.charm.get_ext_mongos_host = mock_get_ext_mongos_host
        for substrate in ["k8s", "vm"]:
            for role in ["mongos", "config-server", "shard"]:
                if role == "mongos" and substrate == "k8s":
                    continue

                assert "node-port" not in self.harness.charm.tls.get_new_sans()["sans_ips"]

    @patch("charm.MongoDBTLS.is_tls_enabled")
    @patch("charms.mongodb.v1.mongodb_tls.subprocess.check_output")
    def test_get_current_sans_returns_none(self, check_output, is_tls_enabled):
        """Tests the different scenarios that get_current_sans returns None.

        1. get_current_sans returns None when TLS is not enabled.
        2. get_current_sans returns None if cert file is wrongly formatted.
        """
        # case 1: get_current_sans returns None when TLS is not enabled.
        is_tls_enabled.return_value = None
        for internal in [True, False]:
            self.assertEqual(self.harness.charm.tls.get_current_sans(internal), None)

        # case 2: get_current_sans returns None if cert file is wrongly formatted.
        check_output.return_value = "".encode("utf-8")
        is_tls_enabled.return_value = True
        for internal in [True, False]:
            self.assertEqual(self.harness.charm.tls.get_current_sans(internal), None)

    @patch("charm.MongoDBTLS.is_tls_enabled")
    @patch("charms.mongodb.v1.mongodb_tls.subprocess.check_output")
    def test_get_current_sans_failure_raises(self, check_output, is_tls_enabled):
        """Tests the difference scenarios in which get_current_sans fails."""
        is_tls_enabled.return_value = True
        check_output.side_effect = subprocess.CalledProcessError(cmd="openssl", returncode=1)

        for internal in [True, False]:
            with self.assertRaises(subprocess.CalledProcessError):
                self.assertEqual(self.harness.charm.tls.get_current_sans(internal), None)

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
        unit_rsa_key = self.harness.charm.get_secret("unit", "ext-key-secret")
        unit_csr = self.harness.charm.get_secret("unit", "ext-csr-secret")

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
        int_rsa_key = self.harness.charm.get_secret("unit", "int-key-secret")
        int_csr = self.harness.charm.get_secret("unit", "int-csr-secret")

        if specific_rsa:
            self.assertEqual(int_rsa_key, expected_rsa)
        else:
            self.assertEqual(int_rsa_key.split("\n")[0], "-----BEGIN RSA PRIVATE KEY-----")

        if specific_csr:
            self.assertEqual(int_csr, expected_csr)
        else:
            self.assertEqual(int_csr.split("\n")[0], "-----BEGIN CERTIFICATE REQUEST-----")
