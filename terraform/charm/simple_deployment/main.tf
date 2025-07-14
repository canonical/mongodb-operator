# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Identify if the current model is where the main orchestrator resides to deploy the tls provider
locals {
  # is_main_orchestrator = !lookup(var.config, "init_hold", false)
  mongodb_role = lookup(var.config, "role", "config-server")
  is_main_orchestrator = local.mongodb_role == "config-server" || local.mongodb_role == ""
}

#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

# Deploy required applications
resource "juju_application" "mongodb" {
  charm {
    name     = "mongodb"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }
  config             = var.config
  model              = var.model
  name               = var.app_name
  units              = var.units
  constraints        = var.constraints
  storage_directives = var.storage

  dynamic "expose" {
    for_each = var.expose ? [1] : []
    content {}
  }

  # TODO: uncomment once final fixes have been added for:
  # Error: juju/terraform-provider-juju#443, juju/terraform-provider-juju#182
  # placement = join(",", var.machines)

  endpoint_bindings = [
    for k, v in var.endpoint_bindings : {
      endpoint = k, space = v
    }
  ]

  lifecycle {
    precondition {
      condition     = local.is_main_orchestrator && (var.main_model == null || var.model == var.main_model) || !local.is_main_orchestrator && var.main_model != null
      error_message = "The main_model should either be null or equal to the model for main orchestrators."
    }
  }
}

# Deploy the self-signed-certificates operator if main orchestrator
resource "juju_application" "self-signed-certificates" {
  for_each = local.is_main_orchestrator ? { "deployed" = true } : {}

  model = var.model

  charm {
    name     = "self-signed-certificates"
    channel  = var.self-signed-certificates.channel
    revision = var.self-signed-certificates.revision
    base     = var.self-signed-certificates.base
  }

  config = var.self-signed-certificates.config

  units       = 1
  constraints = var.self-signed-certificates.constraints
  placement   = length(var.self-signed-certificates.machines) == 1 ? var.self-signed-certificates.machines[0] : null
}


#--------------------------------------------------------
# 2. INTEGRATIONS
#--------------------------------------------------------

# Integrations
resource "juju_integration" "tls-mongodb-same-model_integration" {
  for_each = local.is_main_orchestrator || var.model == var.main_model ? { "local" = true } : {}

  model = var.model

  application {
    name = "self-signed-certificates" # we have to fix the name for subsequent non-main same model apps
  }

  application {
    name = juju_application.mongodb.name
  }

  depends_on = [
    juju_application.self-signed-certificates,
    juju_application.mongodb,
  ]
}
