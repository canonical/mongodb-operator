# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "components" {
  description = "All deployed applications."
  value = merge(
    module.cluster.components,
    {
      data_integrator = juju_application.data_integrator
      s3_integrator   = try(module.s3_integrator[0].application, null)
      gcs_integrator  = try(juju_application.gcs_integrator["deployed"], null)
    }
  )
}

output "models" {
  description = "Models and deployed components managed by this module."
  value = merge(
    {
      config_server = {
        model_uuid = module.cluster.components["config_server"].model_uuid
        components = merge(
          {
            config_server = module.cluster.components["config_server"]
            mongos        = module.cluster.components["mongos"]
          },
          var.shards != null ? {
            for shard_key, shard in var.shards :
            "shard_${shard_key}" => module.cluster.components["shards"][shard_key]
            if shard.model_uuid == module.cluster.components["config_server"].model_uuid
          } : {},
          var.data_integrator.model_uuid == module.cluster.components["config_server"].model_uuid ? {
            data_integrator = juju_application.data_integrator
          } : {},
          try(var.s3_integrator.model_uuid == module.cluster.components["config_server"].model_uuid ? {
            s3_integrator = module.s3_integrator[0].application
          } : {}, {}),
          try(var.gcs_integrator.model_uuid == module.cluster.components["config_server"].model_uuid ? {
            gcs_integrator = juju_application.gcs_integrator["deployed"]
          } : {}, {})
        )
      }
    },
    var.shards != null ? {
      for shard_key, shard in var.shards :
      "shard_${shard_key}" => {
        model_uuid = shard.model_uuid
        components = {
          "shard_${shard_key}" = module.cluster.components["shards"][shard_key]
        }
      }
      if shard.model_uuid != module.cluster.components["config_server"].model_uuid
    } : {},
    var.data_integrator.model_uuid != module.cluster.components["config_server"].model_uuid ? {
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
    try(var.s3_integrator.model_uuid != module.cluster.components["config_server"].model_uuid && var.s3_integrator.model_uuid != var.data_integrator.model_uuid ? {
      s3_integrator = {
        model_uuid = var.s3_integrator.model_uuid
        components = {
          s3_integrator = module.s3_integrator[0].application
        }
      }
    } : {}, {}),
    try(var.gcs_integrator.model_uuid != module.cluster.components["config_server"].model_uuid && var.gcs_integrator.model_uuid != var.data_integrator.model_uuid ? {
      gcs_integrator = {
        model_uuid = var.gcs_integrator.model_uuid
        components = {
          gcs_integrator = juju_application.gcs_integrator["deployed"]
        }
      }
    } : {}, {})
  )
}

output "app_names" {
  description = "Names of of all deployed applications."
  value = merge(
    module.cluster.app_names,
    {
      "data_integrator" : juju_application.data_integrator.name
      "s3_integrator" : try(module.s3_integrator[0].application.name, null)
      "gcs_integrator" : try(juju_application.gcs_integrator["deployed"].name, null)
    }
  )
}

output "provides" {
  description = "Map of all \"provides\" endpoints"
  value       = module.cluster.provides
}

output "requires" {
  description = "Map of all \"requires\" endpoints"
  value       = module.cluster.requires
}

output "offers" {
  description = "Map of all offer endpoints."
  value = merge(
    module.cluster.offers,
    {
      gcs_credentials = try({
        kind = "offer"
        url  = juju_offer.gcs_credentials["offered"].url
      }, null)
      mongos_client = try({
        kind = "offer"
        url  = juju_offer.mongos_client["offered"].url
      }, null)
      s3_credentials = try(module.s3_integrator[0].offers.s3_credentials, null)
    }
  )
}

output "metadata" {
  description = "Metadata of the product deployment."
  value = {
    deployed_at = terraform_data.deployed_at.output
    updated_at  = timestamp()
  }
}
