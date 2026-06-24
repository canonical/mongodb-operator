# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "components" {
  description = "Names of of all deployed applications."
  value = {
    mongodb         = module.mongodb.application.name
    data_integrator = juju_application.data_integrator.name
    s3_integrator   = try(juju_application.s3_integrator["deployed"].name, null)
    gcs_integrator  = try(juju_application.gcs_integrator["deployed"].name, null)
  }
}


# Provided integration endpoints
output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = {
    mongodb_database = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.provides["database"]
    }
    mongodb_cos_agent = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.provides["cos_agent"]
    }
  }
}

# Required integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    mongodb_etcd = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["etcd"]
    }
    mongodb_client_certificates = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["client_certificates"]
    }
    mongodb_gcs_credentials = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["gcs_credentials"]
    }
    mongodb_ldap = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["ldap"]
    }
    mongodb_ldap_certificate_transfer = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["ldap_certificate_transfer"]
    }
    mongodb_peer_certificates = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["peer_certificates"]
    }
    mongodb_s3_credentials = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["s3_credentials"]
    }
    mongodb_vault_kv = {
      name     = module.mongodb.application.name
      endpoint = module.mongodb.requires["vault_kv"]
    }
  }
}

# Offers
output "offers" {
  description = "List of offers URLs."
  value = {
    mongodb_database           = try(juju_offer.mongodb_client["offered"].url, null)
    s3_integrator_credentials  = try(juju_offer.s3_integrator["offered"].url, null)
    gcs_integrator_credentials = try(juju_offer.gcs_integrator["offered"].url, null)
  }
}
