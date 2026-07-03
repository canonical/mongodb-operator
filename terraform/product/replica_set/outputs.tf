# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "components" {
  description = "All deployed applications."
  value = {
    mongodb         = module.mongodb.application
    data_integrator = juju_application.data_integrator
    s3_integrator   = try(module.s3_integrator[0].application, null)
    gcs_integrator  = try(juju_application.gcs_integrator["deployed"], null)
  }
}

output "models" {
  description = "Models and deployed components managed by this module."
  value = merge(
    {
      mongodb = {
        model_uuid = module.mongodb.application.model_uuid
        components = merge(
          {
            mongodb = module.mongodb.application
          },
          var.data_integrator.model_uuid == module.mongodb.application.model_uuid ? {
            data_integrator = juju_application.data_integrator
          } : {},
          try(var.s3_integrator.model_uuid == module.mongodb.application.model_uuid ? {
            s3_integrator = module.s3_integrator[0].application
          } : {}, {}),
          try(var.gcs_integrator.model_uuid == module.mongodb.application.model_uuid ? {
            gcs_integrator = juju_application.gcs_integrator["deployed"]
          } : {}, {})
        )
      }
    },
    var.data_integrator.model_uuid != module.mongodb.application.model_uuid ? {
      data_integrator = {
        model_uuid = var.data_integrator.model_uuid
        components = merge(
          {
            data_integrator = juju_application.data_integrator
          },
          try(var.s3_integrator.model_uuid == var.data_integrator.model_uuid ? {
            s3_integrator = module.s3_integrator[0].application
          } : {}, {}),
          try(var.gcs_integrator.model_uuid == var.data_integrator.model_uuid ? {
            gcs_integrator = juju_application.gcs_integrator["deployed"]
          } : {}, {})
        )
      }
    } : {},
    try(var.s3_integrator.model_uuid != module.mongodb.application.model_uuid && var.s3_integrator.model_uuid != var.data_integrator.model_uuid ? {
      s3_integrator = {
        model_uuid = var.s3_integrator.model_uuid
        components = {
          s3_integrator = module.s3_integrator[0].application
        }
      }
    } : {}, {}),
    try(var.gcs_integrator.model_uuid != module.mongodb.application.model_uuid && var.gcs_integrator.model_uuid != var.data_integrator.model_uuid ? {
      gcs_integrator = {
        model_uuid = var.gcs_integrator.model_uuid
        components = {
          gcs_integrator = juju_application.gcs_integrator["deployed"]
        }
      }
    } : {}, {})
  )
}


# Provided integration endpoints
output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = {
    mongodb_database  = module.mongodb.provides["database"]
    mongodb_cos_agent = module.mongodb.provides["cos_agent"]
  }
}

# Required integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    mongodb_client_certificates       = module.mongodb.requires["client_certificates"]
    mongodb_etcd                      = module.mongodb.requires["etcd"]
    mongodb_gcs_credentials           = module.mongodb.requires["gcs_credentials"]
    mongodb_ldap                      = module.mongodb.requires["ldap"]
    mongodb_ldap_certificate_transfer = module.mongodb.requires["ldap_certificate_transfer"]
    mongodb_peer_certificates         = module.mongodb.requires["peer_certificates"]
    mongodb_s3_credentials            = module.mongodb.requires["s3_credentials"]
    mongodb_vault_kv                  = module.mongodb.requires["vault_kv"]
  }
}

# Offers
output "offers" {
  description = "List of offers URLs."
  value = {
    mongodb_database = try({
      kind = "offer"
      name = module.mongodb.application.name
      url  = juju_offer.mongodb_client["offered"].url
    }, null)
    s3_integrator_credentials = try({
      kind = "offer"
      name = module.s3_integrator[0].application.name
      url  = module.s3_integrator[0].offers.s3_credentials
    }, null)
    gcs_integrator_credentials = try({
      kind = "offer"
      name = juju_application.gcs_integrator["deployed"].name
      url  = juju_offer.gcs_integrator["offered"].url
    }, null)
  }
}

output "metadata" {
  description = "Metadata of the product deployment."
  value = {
    deployed_at = terraform_data.deployed_at.output
    updated_at  = timestamp()
  }
}
