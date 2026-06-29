# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

# Names of deployed applications
output "components" {
  description = "All deployed applications."
  value = {
    config_server = module.config_server.application
    shards = [
      for shard_module in module.shards : shard_module.application
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
    gcs_credentials           = "gcs-credentials"
    ldap                      = "ldap"
    ldap_certificate_transfer = "ldap-certificate-transfer"
    etcd                      = "etcd"
    vault_kv                  = "vault-kv"
  }
}

# Offers
output "offers" {
  description = "List of offers URLs."
  value = {
    config_server = try(juju_offer.mongodb_config_server_offer["offered"].url, null)
    config_server_cluster = juju_offer.cluster.url
    config_server_cos_agent = juju_offer.cos_agent.url
  }
}
