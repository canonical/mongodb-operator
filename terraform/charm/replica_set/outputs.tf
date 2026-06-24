# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "Object representing the deployed MongoDB application."
  value       = juju_application.mongodb
}


# Provided integration endpoints
output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = {
    database      = "database"
    cluster       = "cluster"
    config_server = "config-server"
    cos_agent     = "cos-agent"
  }
}

# Required integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    client_certificates       = "client-certificates"
    etcd                      = "etcd"
    gcs_credentials           = "gcs-credentials"
    ldap                      = "ldap"
    ldap_certificate_transfer = "ldap-certificate-transfer"
    peer_certificates         = "peer-certificates"
    sharding                  = "sharding"
    s3_credentials            = "s3-credentials"
    vault_kv                  = "vault-kv"
  }
}
