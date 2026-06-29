# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_names" {
  description = "Names of of all deployed applications."
  value = merge(
    module.mongodb.app_names,
    {
      "data_integrator" : juju_application.data_integrator.name
      "s3_integrator" : juju_application.s3_integrator.name
      "self_signed_certificates" : var.self_signed_certificates != null ? juju_application.self-signed-certificates["deployed"].name : null
      "vault" : var.vault != null ? juju_application.vault["deployed"].name : null
      "mongos" : juju_application.mongos.name
      "grafana_agent" : [
        for i in range(length(local.mongodb_apps)) :
        juju_application.grafana_agent[i].name
      ]
    }
  )
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
    peer_certificates         = "peer-certificates"
    client_certificates       = "client-certificates"
    s3_credentials            = "s3-credentials"
    ldap                      = "ldap"
    ldap_certificate_transfer = "ldap-certificate-transfer"
    vault_kv                  = "vault-kv"
  }
}

# Offers
output "offers" {
  description = "List of offers URLs."
  value = merge(
    module.mongodb.offers,
    {
      "config_server_mongos" : try(juju_offer.config_server_mongos_offer["offered"].url, null),
      "tls_provider" : try(juju_offer.tls_provider_offer["offered"].url, null),
      "s3_credentials" : try(juju_offer.s3_integrator_offer["offered"].url, null),
      "vault_kv" : try(juju_offer.vault_provider_offer["offered"].url, null)
    }
  )
}
