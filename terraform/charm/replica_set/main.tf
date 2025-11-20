# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "mongodb" {
  charm {
    name     = "mongodb"
    channel  = var.channel
    revision = var.revision
    base     = var.base
  }
  config             = var.config
  name               = var.app_name
  units              = (var.machines == null || length(var.machines) == 0) ? var.units : null
  machines           = (var.machines == null || length(var.machines) == 0) ? null : var.machines
  constraints        = var.constraints
  storage_directives = var.storage
  endpoint_bindings  = var.endpoint_bindings

  dynamic "expose" {
    for_each = var.expose != null ? [1] : []
    content {
      cidrs     = try(var.expose.cidr, null)
      endpoints = try(var.expose.endpoints, null)
      spaces    = try(var.expose.spaces, null)
    }
  }
  model_uuid = var.model_uuid
}
