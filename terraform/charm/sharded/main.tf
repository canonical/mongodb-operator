# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  apps = [
    for app in concat(var.apps != null ? var.apps : []) : app if app != null
  ]

  apps_not_in_main_model = [
    for app in concat([var.sharded], local.apps) :
    app if app != null && app.model != var.config-server.model
  ]
  apps_not_in_failover_model = [
    for app in local.apps :
    app if app.model != var.sharded.model
  ]

  all_models = distinct(concat(
    [var.config-server.model],
    var.sharded != null ? [var.sharded.model] : [],
    var.apps != null ? [for app in var.apps : app.model] : [],
  ))
}

#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

# main orchestrator opensearch app
module "config-server" {
  source = "../simple_deployment"

  channel  = var.config-server.channel
  revision = var.config-server.revision
  base     = var.config-server.base

  app_name          = var.config-server.app_name
  units             = var.config-server.units
  config            = var.config-server.config
  model             = var.config-server.model
  constraints       = var.config-server.constraints
  storage           = var.config-server.storage
  endpoint_bindings = var.config-server.endpoint_bindings
  expose            = var.config-server.expose

  self-signed-certificates = var.self-signed-certificates
}

# failover orchestrator opensearch app
module "sharded" {
  for_each = var.sharded != null ? { "deployed" = true } : {}
  source   = "../simple_deployment"

  # required to flag whether this app is in the same model as the main orchestrator for TLS relation
  main_model = var.config-server.model

  channel  = var.sharded.channel
  revision = var.sharded.revision
  base     = var.sharded.base

  app_name          = var.sharded.app_name
  units             = var.sharded.units
  config            = merge(var.sharded.config, { "init_hold" : "true" })
  model             = var.sharded.model
  constraints       = var.sharded.constraints
  storage           = var.sharded.storage
  endpoint_bindings = var.sharded.endpoint_bindings
  expose            = var.sharded.expose
}

# all non orchestrator apps
module "mongodb_non_orchestrator_apps" {
  for_each = { for idx, app in local.apps : idx => app if app != null }
  source   = "../simple_deployment"

  # required to flag whether this app is in the same model as the main orchestrator for TLS relation
  main_model = var.config-server.model

  channel  = each.value.channel
  revision = each.value.revision
  base     = each.value.base

  app_name    = each.value.app_name
  units       = each.value.units
  config      = merge(each.value.config, { "init_hold" : "true" })
  model       = each.value.model
  constraints = each.value.constraints
  storage     = each.value.storage
  expose      = each.value.expose
}

#--------------------------------------------------------
# 2. OFFERS (if cross model)
#--------------------------------------------------------

# offer TLS certificates if needed
resource "juju_offer" "self_signed_certificates-offer" {
  for_each = length(local.all_models) > 1 ? { "offered" = true } : {}

  model            = var.config-server.model
  application_name = "self-signed-certificates"
  endpoints        = ["certificates"]
}

resource "juju_offer" "config-server-offer" {
  for_each = length(local.all_models) > 1 ? { "offered" = true } : {}

  model            = var.config-server.model
  application_name = var.config-server.app_name
  endpoints        = ["database"]
}

resource "juju_offer" "sharded-offer" {
  for_each = var.sharded != null && length(local.apps_not_in_failover_model) > 1 ? { "offered" = true } : {}

  model            = var.sharded.model
  application_name = var.sharded.app_name
  endpoints        = ["sharding"]
}


#--------------------------------------------------------
# 3. INTEGRATIONS
#--------------------------------------------------------

# For CROSS-MODEL TLS integrations
resource "juju_integration" "tls-config-server-cross_model-integration" {
  # Only if cross-model
  for_each = { for app in local.apps_not_in_main_model : app.app_name => app }
  model    = each.value.model

  application {
    offer_url = juju_offer.self_signed_certificates-offer["offered"].url
  }
  application {
    name = each.value.app_name
  }

  depends_on = [
    module.config-server,
    juju_offer.self_signed_certificates-offer,
  ]
}

# large deployments cluster integrations with main orchestrator
resource "juju_integration" "cluster-main-cross_model-relation" {
  for_each = { for app in local.apps_not_in_main_model : app.app_name => app }
  model    = each.value.model

  application {
    name     = each.value.app_name
    endpoint = "database"
  }
  application {
    offer_url = juju_offer.config-server-offer["offered"].url
  }

  depends_on = [
    module.config-server,
    module.sharded,
    juju_offer.config-server-offer,
  ]
}

# large deployments peer-cluster integrations with failover orchestrator if any
resource "juju_integration" "cluster-sharded-cross_model-relation" {
  for_each = var.sharded != null ? { for app in local.apps_not_in_failover_model : app.app_name => app } : {}
  model    = each.value.model

  application {
    name     = each.value.app_name
    endpoint = "sharding"
  }
  application {
    offer_url = juju_offer.sharded-offer["offered"].url
  }

  depends_on = [
    module.sharded,
    juju_offer.sharded-offer,
  ]
}

# SAME-MODEL integration between config-server and sharded
resource "juju_integration" "config-server-sharded-same-model" {
  for_each = var.sharded != null && var.sharded.model == var.config-server.model ? { "local" = true } : {}
  model    = var.config-server.model

  application {
    name     = var.config-server.app_name
    endpoint = "config-server"
  }
  application {
    name     = var.sharded.app_name
    endpoint = "sharding"
  }

  depends_on = [
    module.config-server,
    module.sharded,
  ]
}

resource "juju_integration" "config-server-apps-sharded-same-model" {
  for_each = {
    for app in (var.apps != null ? var.apps : []) : app.app_name => app
    if app != null && 
       lookup(app.config, "role", "shard") == "shard" && 
       app.model == var.config-server.model
  }
  model = var.config-server.model

  application {
    name     = var.config-server.app_name
    endpoint = "config-server"
  }
  application {
    name     = each.value.app_name
    endpoint = "sharding"
  }

  depends_on = [
    module.config-server,
  ]
}