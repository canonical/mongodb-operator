# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  cos_agent_enabled           = var.cos_agent_integration != null ? true : false
  encryption_at_rest_enabled  = var.vault_kv_integration != null ? true : false
  etcd_rolling_ops_enabled    = var.etcd_integration != null ? true : false
  client_certificates_enabled = var.client_certificates_integration != null ? true : false
  ldap_enabled                = var.ldap_integration != null && var.ldap_certificate_transfer_integration != null ? true : false
  peer_certificates_enabled   = var.peer_certificates_integration != null ? true : false

  backup_integrations = compact([
    var.s3_integrator != null ? "s3_integrator" : "",
    var.gcs_integrator != null ? "gcs_integrator" : "",
  ])

  ldap_integrations = compact([
    var.ldap_integration != null ? "ldap_integration" : "",
    var.ldap_certificate_transfer_integration != null ? "ldap_certificate_transfer_integration" : "",
  ])
}


resource "terraform_data" "deployed_at" {
  input = timestamp()

  lifecycle {
    ignore_changes = [input]
  }
}
