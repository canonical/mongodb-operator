# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  s3_integrator_enabled = var.backups_integrator != null ? true : false
  cos_agent_enabled     = var.cos_agent_integration != null ? true : false
  certificates_enabled  = var.certificates_integration != null ? true : false
  ldap_enabled          = var.ldap_integration != null && var.ldap_certificate_transfer_integration != null ? true : false

  ldap_integrations = compact([
    var.ldap_integration != null ? "ldap_integration" : "",
    var.ldap_certificate_transfer_integration != null ? "ldap_certificate_transfer_integration" : "",
  ])

  model_components = concat(
    [
      {
        key        = "mongodb"
        model_uuid = module.mongodb.application.model_uuid
        value      = module.mongodb.application
      },
      {
        key        = "data_integrator"
        model_uuid = module.data_integrator.application.model_uuid
        value      = module.data_integrator.application
      },
    ],
    local.s3_integrator_enabled ? [
      {
        key        = "s3_integrator"
        model_uuid = module.s3_integrator[0].application.model_uuid
        value      = module.s3_integrator[0].application
      }
    ] : [],
  )
}


resource "terraform_data" "deployed_at" {
  input = timestamp()

  lifecycle {
    ignore_changes = [input]
  }
}
