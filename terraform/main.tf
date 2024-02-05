# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "mongodb-k8s" {
  name  = var.app_name
  model = var.model_name

  charm {
    name    = "mongodb-k8s"
    channel = var.channel
    base    = "ubuntu@22.04"
  }
  config = var.config
  units  = 1
  trust  = true
}
