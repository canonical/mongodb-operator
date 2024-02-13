# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "mongodb" {
  name  = var.app_name
  model = var.model_name

  charm {
    name    = "mongodb"
    channel = var.channel
    base    = "ubuntu@22.04"
  }
  config = var.mongo-config
  units  = 1
  trust  = true
}
