# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

# Replica set MongoDB app
module "mongodb" {
  source = "../../charms/mongodb"

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

resource "juju_secret" "s3_secret" {
  count      = var.s3_integrator != null && var.s3_access_key != null && var.s3_secret_key != null ? 1 : 0
  model_uuid = var.s3_integrator.model_uuid
  name       = "${var.s3_integrator.app_name}-credentials"
  value = {
    access-key = var.s3_access_key
    secret-key = var.s3_secret_key
  }
  info = "S3 credentials for ${var.s3_integrator.app_name}"
}

module "s3_integrator" {
  depends_on = [juju_secret.s3_secret]
  count      = var.s3_integrator != null ? 1 : 0
  source     = "../../charms/s3_integrator"

  app_name = var.s3_integrator.app_name
  base     = var.s3_integrator.base
  channel  = var.s3_integrator.channel
  config = merge(
    var.s3_integrator.config,
    length(juju_secret.s3_secret) > 0 ? {
      credentials = juju_secret.s3_secret[0].secret_uri
    } : {}
  )
  constraints = var.s3_integrator.constraints
  model_uuid  = var.s3_integrator.model_uuid
  revision    = var.s3_integrator.revision
  units       = var.s3_integrator.units
}

resource "juju_access_secret" "s3_secret_access" {
  depends_on = [juju_secret.s3_secret, module.s3_integrator]
  count      = length(juju_secret.s3_secret) > 0 ? 1 : 0
  model_uuid = var.s3_integrator.model_uuid
  applications = [
    module.s3_integrator[0].application.name
  ]
  secret_id = juju_secret.s3_secret[0].secret_id
}
