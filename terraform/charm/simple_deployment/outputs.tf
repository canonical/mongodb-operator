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
    mongodb               = juju_application.mongodb.name
    self-signed-certificates = try(juju_application.self-signed-certificates["deployed"].name, null)
  }
}
