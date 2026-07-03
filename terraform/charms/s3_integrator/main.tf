# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "s3_integrator" {
  name       = var.app_name
  model_uuid = var.model_uuid
  charm {
    name     = "s3-integrator"
    base     = var.base
    channel  = var.channel
    revision = var.revision
  }
  config      = var.config
  units       = var.units
  constraints = var.constraints
}

resource "juju_offer" "s3_credentials" {
  model_uuid       = var.model_uuid
  application_name = juju_application.s3_integrator.name
  endpoints        = ["s3-credentials"]
  depends_on       = [juju_application.s3_integrator]
}
