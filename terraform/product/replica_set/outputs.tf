# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_names" {
  description = "Names of of all deployed applications."
  value = {
    mongodb                  = module.mongodb.app_names["mongodb"]
    data_integrator          = juju_application.s3_integrator.name
    s3_integrator            = juju_application.s3_integrator.name
    grafana_agent            = juju_application.grafana_agent.name
    self_signed_certificates = var.self_signed_certificates != null ? juju_application.self-signed-certificates["deployed"].name : null
  }
}


# Provided integration endpoints
output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = {
    database      = "database"
    config_server = "config-server"
    cluster       = "cluster"
    cos_agent     = "cos-agent"
  }
}

# Required integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    sharding                  = "sharding"
    certificates              = "certificates"
    s3_credentials            = "s3-credentials"
    ldap                      = "ldap"
    ldap_certificate_transfer = "ldap-certificate-transfer"
  }
}

# Offers
output "offers" {
  description = "List of offers URLs."
  value = {
    mongodb_client  = try(juju_offer.mongodb_client_offer["offered"].url, null)
    tls_provider    = try(juju_offer.tls_provider_offer["offered"].url, null)
    s3_credentials  = try(juju_offer.s3_integrator_offer["offered"].url, null)
  }
}
