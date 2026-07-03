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
  value = {
    for model_uuid in distinct([for component in local.model_components : component.model_uuid]) :
    model_uuid => {
      model_uuid = model_uuid
      components = merge([
        for component in local.model_components :
        { (component.key) = component.value }
        if component.model_uuid == model_uuid
      ]...)
    }
  }
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
