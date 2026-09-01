# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "Object representing the deployed MongoDB application."
  value       = juju_application.mongodb
}

output "offers" {
  description = "Map of all offers exposed by the single charm."
  value       = {}
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
    certificates = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "certificates"
    }
    gcs_credentials = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "gcs-credentials"
    }
    ldap = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "ldap"
    }
    ldap_certificate_transfer = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "ldap-certificate-transfer"
    }
    sharding = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "sharding"
    }
    s3_credentials = {
      kind     = "endpoint"
      name     = juju_application.mongodb.name
      endpoint = "s3-credentials"
    }
  }
}
