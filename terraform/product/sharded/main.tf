# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

# Sharded cluster deployment
# module "mongodb" {
#   source = "../../charm/sharded"
#
#   config_server = merge(var.config_server, {
#     config = merge(var.config_server.config, local.enable_encryption_rest ? { "enable-encryption-at-rest" : "true" } : {})
#   })
#   shards = var.shards != null ? [
#     for shard in var.shards :
#     merge(shard, {
#       config = merge(shard.config, local.enable_encryption_rest ? { "enable-encryption-at-rest" : "true" } : {})
#     })
#   ] : []
# }

# MongoDB config server app
module "config_server" {
  source = "../../charm/replica_set"

  app_name           = var.config_server.app_name
  base               = var.config_server.base
  channel            = var.config_server.channel
  config             = merge(var.config_server.config, { "role" : "config-server" }, local.encryption_at_rest_enabled ? { "enable-encryption-at-rest" : "true" } : {})
  constraints        = var.config_server.constraints
  endpoint_bindings  = var.config_server.endpoint_bindings
  expose             = var.config_server.expose
  machines           = var.config_server.machines
  model_uuid         = var.config_server.model_uuid
  revision           = var.config_server.revision
  storage_directives = var.config_server.storage_directives
  units              = var.config_server.units
}

# Shard apps
module "shards" {
  for_each = { for idx, app in local.shards : idx => app if app != null }
  source   = "../../charm/replica_set"

  app_name           = each.value.app_name
  base               = each.value.base
  channel            = each.value.channel
  config             = merge(each.value.config, { "role" : "shard" }, local.encryption_at_rest_enabled ? { "enable-encryption-at-rest" : "true" } : {})
  constraints        = each.value.constraints
  endpoint_bindings  = each.value.endpoint_bindings
  expose             = each.value.expose
  machines           = each.value.machines
  model_uuid         = each.value.model_uuid
  revision           = each.value.revision
  storage_directives = each.value.storage_directives
  units              = each.value.units
}


# mongos
resource "juju_application" "mongos" {
  charm {
    name     = "mongos"
    channel  = var.mongos.channel
    revision = var.mongos.revision
    base     = var.mongos.base
  }

  name       = var.mongos.app_name
  config     = var.mongos.config
  model_uuid = var.mongos.model_uuid
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
