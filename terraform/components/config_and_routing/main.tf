# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

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

module "mongos" {
  source = "git::https://github.com/canonical/mongos-operator//terraform?ref=8-transition/edge"

  app_name          = var.mongos.app_name
  base              = var.mongos.base
  channel           = var.mongos.channel
  config            = var.mongos.config
  endpoint_bindings = var.mongos.endpoint_bindings
  model_uuid        = module.config_server.application.model_uuid
  revision          = var.mongos.revision
}
