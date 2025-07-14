# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  all_models = distinct(concat(
    [var.config-server.model],
    var.sharded != null ? [var.sharded.model] : [],
    var.apps != null ? [for app in var.apps : app.model] : [],
  ))

  
  mongodb_apps_per_model = {
    for model in local.all_models : model => flatten(concat(
      model == var.config-server.model ? [var.config-server.app_name] : [],
      var.sharded != null && model == var.sharded ? [var.sharded.app_name] : [],
      var.apps != null ? [for app in var.apps : app.app_name if app.model == model] : [],
    ))
  }
}

module "config-server" {
    source = "../../charm/sharded"
    config-server = var.config-server
    sharded = var.sharded
    apps = var.apps
    self-signed-certificates = var.self-signed-certificates
  
}

# data-integrator in the main model
resource "juju_application" "data-integrator" {
  charm {
    name     = "data-integrator"
    channel  = var.data-integrator.channel
    revision = var.data-integrator.revision
    base     = var.data-integrator.base
  }
  model  = var.config-server.model
  config = var.data-integrator.config

  constraints = var.data-integrator.constraints
  placement   = length(var.data-integrator.machines) == 1 ? var.data-integrator.machines[0] : null
}

resource "juju_application" "backups-integrator" {
  charm {
    name     = "${var.backups-integrator.storage_type}-integrator"
    channel  = var.backups-integrator.channel
    revision = var.backups-integrator.revision
    base     = var.backups-integrator.base
  }
  model  = var.config-server.model
  config = var.backups-integrator.config

  constraints = var.backups-integrator.constraints
  placement   = length(var.backups-integrator.machines) == 1 ? var.backups-integrator.machines[0] : null
}

resource "juju_application" "grafana_agents" {
  for_each = toset(local.all_models)

  charm {
    name     = "grafana-agent"
    channel  = var.grafana-agent.channel
    revision = var.grafana-agent.revision
    base     = var.grafana-agent.base
  }
  model  = each.value
  config = var.grafana-agent.config
}

resource "juju_application" "mongos" {
  charm {
    name = "mongos"
    channel = var.mongos.channel
    revision = var.mongos.revision
    base = var.mongos.base
  }
  model = var.config-server.model
  config = var.mongos.config
}

resource "juju_integration" "data-integrator_mongos-integration" {
  model = var.config-server.model
  application {
    name = juju_application.data-integrator.name
  }
  application {
    name = juju_application.mongos.name
  }
}

resource "juju_integration" "config-server_mongos-integration" {
  model = var.config-server.model
  application {
    name = var.config-server.app_name
  }
  application {
    name = juju_application.mongos.name
  }
}

resource "juju_integration" "self-signed-certificates_mongos-integration" {
  model = var.config-server.model
  application {
    name = var.self-signed-certificates.app_name
  }
  application {
    name = juju_application.mongos.name
  }
}

## Grafana integration:

resource "juju_integration" "grafana-agent_config-server-integration" {
  model = var.config-server.model
  application {
    name = var.config-server.app_name
  }
  application {
    name = juju_application.grafana_agents[var.config-server.model].name
  }
}

resource "juju_integration" "grafana-agent_sharded-integration" {
  model = var.config-server.model
  application {
    name = var.sharded.app_name
  }
  application {
    name = juju_application.grafana_agents[var.config-server.model].name
  }
}

resource "juju_integration" "grafana-agent_apps-integration" {
  for_each = { for app in var.apps : "${app.model}-${app.app_name}" => app }
  model = each.value.model
  application {
    name = each.value.app_name
  }
  application {
    name = juju_application.grafana_agents[each.value.model].name
  }
}

resource "juju_integration" "grafana-agent_self-signed-certificates-integration" {
  model = var.config-server.model
  application {
    name = "self-signed-certificates"
  }
  application {
    name = juju_application.grafana_agents[var.config-server.model].name
  }
}

resource "juju_integration" "grafana-agent_data-integrator-integration" {
  model = var.config-server.model
  application {
    name = juju_application.data-integrator.name
  }
  application {
    name = juju_application.grafana_agents[var.config-server.model].name
  }
}

resource "juju_integration" "grafana-agent_backups-integrator-integration" {
  model = var.config-server.model
  application {
    name = juju_application.backups-integrator.name
  }
  application {
    name = juju_application.grafana_agents[var.config-server.model].name
  }
}