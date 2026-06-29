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
    database = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "database"
    }
    cluster = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "cluster"
    }
    config_server = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "config-server"
    }
    cos_agent = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "cos-agent"
    }
  }
}

# Required integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    client_certificates = {
      name     = juju_application.mongodb.name
      endpoint = "client-certificates"
    }
    etcd = {
      name     = juju_application.mongodb.name
      endpoint = "etcd"
    }
    gcs_credentials = {
      name     = juju_application.mongodb.name
      endpoint = "gcs-credentials"
    }
    ldap = {
      name     = juju_application.mongodb.name
      endpoint = "ldap"
    }
    ldap_certificate_transfer = {
      name     = juju_application.mongodb.name
      endpoint = "ldap-certificate-transfer"
    }
    peer_certificates = {
      name     = juju_application.mongodb.name
      endpoint = "peer-certificates"
    }
    sharding = {
      name     = juju_application.mongodb.name
      endpoint = "sharding"
    }
    s3_credentials = {
      name     = juju_application.mongodb.name
      endpoint = "s3-credentials"
    }
    vault_kv = {
      name     = juju_application.mongodb.name
      endpoint = "vault-kv"
    }
  }
}
