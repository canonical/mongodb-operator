# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    sharding       = "shards"
    certificates   = "tls-certificates"
    s3_credentials = "s3"
  }
}

output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = {
    database       = "mongodb_client"
    config-server  = "shards"
    cos_agent      = "cos-agent"
    cluster        = "config-server"
  }
}

output "app_names" {
  description = "Output of all deployed application names."
  value = {
    config-server     = module.config-server.app_names["mongodb"]
    sharded           = module.sharded.app_names["mongodb"]
    opensearch_apps = [
      for app_module in module.mongodb_non_orchestrator_apps :
      app_module.app_names["mongodb"]
    ]
    self-signed-certificates = module.config-server.app_names["self-signed-certificates"]
  }
}

output "offers" {
  description = "List of offers URLs."
  value = {
    config-server     = try(juju_offer.config-server-offer["offered"].url, null)
    sharded           = try(juju_offer.sharded-offer["offered"].url, null)
    certificates      = try(juju_offer.self_signed_certificates-offer["offered"].url, null)
  }
}
