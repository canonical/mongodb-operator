# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "data_integrator" {
  charm {
    name     = "data-integrator"
    base     = var.base
    channel  = var.channel
    revision = var.revision
  }

  config             = var.config
  constraints        = var.constraints
  endpoint_bindings  = var.endpoint_bindings
  machines           = (var.machines == null || length(var.machines) == 0) ? null : var.machines
  model_uuid         = var.model_uuid
  name               = var.app_name
  storage_directives = var.storage_directives
  units              = (var.machines == null || length(var.machines) == 0) ? var.units : null
}
