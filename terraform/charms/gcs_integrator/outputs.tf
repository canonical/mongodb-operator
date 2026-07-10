# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "application" {
  description = "Object representing the deployed application."
  value       = juju_application.gcs_integrator
}

output "offers" {
  description = "Map of all offers exposed by the single charm."
  value = {
    gcs_credentials = {
      kind = "offer"
      url  = juju_offer.gcs_credentials.url
    }
  }
}


output "provides" {
  description = "Provides endpoints."
  value = {
    gcs_credentials = {
      kind     = "endpoint"
      name     = juju_application.gcs_integrator.name
      endpoint = "gcs-credentials"
    }
  }
}

output "requires" {
  description = "Map of all \"requires\" endpoints"
  value       = {}
}
