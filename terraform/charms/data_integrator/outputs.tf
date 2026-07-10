# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "Object representing the deployed application."
  value       = juju_application.data_integrator
}

output "offers" {
  description = "Map of all offers exposed by the single charm."
  value       = {}
}

output "provides" {
  description = "Provides endpoints."
  value = {
    mongos = {
      kind     = "endpoint"
      name     = juju_application.data_integrator.name
      endpoint = "mongos"
    }
  }
}

output "requires" {
  description = "Requires endpoints."
  value = {
    mongodb = {
      kind     = "endpoint"
      name     = juju_application.data_integrator.name
      endpoint = "mongodb"
    }
  }
}