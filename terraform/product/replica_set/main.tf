# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

# Replica set MongoDB app
module "mongodb" {
  source = "../../charm/mongodb"

  app_name           = var.mongodb.app_name
  base               = var.mongodb.base
  channel            = var.mongodb.channel
  config             = merge(var.mongodb.config, { "role" : "replication" }, local.encryption_at_rest_enabled ? { "enable-encryption-at-rest" : "true" } : {})
  constraints        = var.mongodb.constraints
  endpoint_bindings  = var.mongodb.endpoint_bindings
  expose             = var.mongodb.expose
  machines           = var.mongodb.machines
  model_uuid         = var.mongodb.model_uuid
  revision           = var.mongodb.revision
  storage_directives = var.mongodb.storage_directives
  units              = var.mongodb.units
}


resource "terraform_data" "validate_backup_integrations" {
  input = local.backup_integrations

  lifecycle {
    precondition {
      condition     = length(local.backup_integrations) <= 1
      error_message = "Only one backup integrator can be configured: set either s3_integrator or gcs_integrator, not both."
    }
  }
}

resource "terraform_data" "validate_ldap_integrations" {
  input = local.ldap_integrations

  lifecycle {
    precondition {
      condition     = length(local.ldap_integrations) == 0 || length(local.ldap_integrations) == 2
      error_message = "LDAP integrations must be configured together: set both ldap_integration and ldap_certificate_transfer_integration, or neither."
    }
  }
}

# Integrator apps
resource "juju_application" "data_integrator" {
  charm {
    name     = "data-integrator"
    channel  = var.data_integrator.channel
    revision = var.data_integrator.revision
    base     = var.data_integrator.base
  }

  name               = var.data_integrator.app_name
  config             = var.data_integrator.config
  constraints        = var.data_integrator.constraints
  endpoint_bindings  = var.data_integrator.endpoint_bindings
  machines           = (var.data_integrator.machines == null || length(var.data_integrator.machines) == 0) ? null : var.data_integrator.machines
  model_uuid         = var.data_integrator.model_uuid
  storage_directives = var.data_integrator.storage_directives
  units              = (var.data_integrator.machines == null || length(var.data_integrator.machines) == 0) ? var.data_integrator.units : null
}

resource "juju_application" "gcs_integrator" {
  for_each = var.gcs_integrator != null ? { "deployed" = var.gcs_integrator } : {}

  charm {
    name     = "gcs-integrator"
    channel  = each.value.channel
    revision = each.value.revision
    base     = each.value.base
  }

  name               = each.value.app_name
  config             = each.value.config
  constraints        = each.value.constraints
  endpoint_bindings  = each.value.endpoint_bindings
  machines           = (each.value.machines == null || length(each.value.machines) == 0) ? null : each.value.machines
  model_uuid         = each.value.model_uuid
  storage_directives = each.value.storage_directives
  units              = (each.value.machines == null || length(each.value.machines) == 0) ? each.value.units : null
}

resource "juju_application" "s3_integrator" {
  for_each = var.s3_integrator != null ? { "deployed" = var.s3_integrator } : {}

  charm {
    name     = "s3-integrator"
    channel  = each.value.channel
    revision = each.value.revision
    base     = each.value.base
  }

  name               = each.value.app_name
  config             = each.value.config
  constraints        = each.value.constraints
  endpoint_bindings  = each.value.endpoint_bindings
  machines           = (each.value.machines == null || length(each.value.machines) == 0) ? null : each.value.machines
  model_uuid         = each.value.model_uuid
  storage_directives = each.value.storage_directives
  units              = (each.value.machines == null || length(each.value.machines) == 0) ? each.value.units : null
}
