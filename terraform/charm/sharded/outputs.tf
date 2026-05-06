# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Names of deployed applications
output "app_names" {
  description = "Names of of all deployed applications."
  value = {
    mongodb_config_server = module.mongodb_config_server.app_names["mongodb"]
    shards = [
      for shard_module in module.mongodb_shards : shard_module.app_names["mongodb"]
    ]
  }
}

# Provided integration endpoints
output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = {
    database      = "database"
    config_server = "config-server"
    cluster       = "cluster"
    cos_agent     = "cos-agent"
  }
}

# Required integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    sharding                  = "sharding"
    peer_certificates         = "peer-certificates"
    client_certificates       = "client-certificates"
    s3_credentials            = "s3-credentials"
    ldap                      = "ldap"
    ldap_certificate_transfer = "ldap-certificate-transfer"
    etcd                      = "etcd"
  }
}

# Offers
output "offers" {
  description = "List of offers URLs."
  value = {
    mongodb_config_server = try(juju_offer.mongodb_config_server_offer["offered"].url, null)
  }
}
