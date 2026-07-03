# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

# config server mongodb app
module "config_server" {
  source = "../../charms/mongodb"

  app_name           = var.config_server.app_name
  base               = var.config_server.base
  channel            = var.config_server.channel
  config             = merge(var.config_server.config, { "role" : "config-server" })
  constraints        = var.config_server.constraints
  endpoint_bindings  = var.config_server.endpoint_bindings
  expose             = var.config_server.expose
  machines           = var.config_server.machines
  model_uuid         = var.config_server.model_uuid
  revision           = var.config_server.revision
  storage_directives = var.config_server.storage_directives
  units              = var.config_server.units
}

# shard apps
module "shards" {
  for_each = { for idx, app in local.shards : idx => app if app != null }
  source   = "../../charms/mongodb"

  app_name           = each.value.app_name
  base               = each.value.base
  channel            = each.value.channel
  config             = merge(each.value.config, { "role" : "shard" })
  constraints        = each.value.constraints
  endpoint_bindings  = each.value.endpoint_bindings
  expose             = each.value.expose
  machines           = each.value.machines
  model_uuid         = each.value.model_uuid
  revision           = each.value.revision
  storage_directives = each.value.storage_directives
  units              = each.value.units
}

module "mongos" {
  source = "git::https://github.com/canonical/mongos-operator//terraform?ref=DPE-10295"

  app_name          = var.mongos.app_name
  base              = var.mongos.base
  channel           = var.mongos.channel
  config            = var.mongos.config
  endpoint_bindings = var.mongos.endpoint_bindings
  machines          = var.mongos.machines
  model_uuid        = module.config_server.application.model_uuid
  revision          = var.mongos.revision
}
