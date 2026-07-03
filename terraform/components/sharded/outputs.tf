# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "components" {
  description = "All deployed applications."
  value = {
    config_server = module.config_server.application
    mongos        = module.mongos.application
    shards = [
      for shard_module in module.shards : shard_module.application
    ]
  }
}

output "app_names" {
  description = "Names of of all deployed applications."
  value = {
    config_server = module.config_server.application.name
    mongos        = module.mongos.application.name
    shards = [
      for shard_module in module.shards : shard_module.application.name
    ]
  }
}

output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = merge(
    {
      config_server           = module.config_server.provides["config_server"]
      config_server_cluster   = module.config_server.provides["cluster"]
      config_server_cos_agent = module.config_server.provides["cos_agent"]
    },
    length(module.shards) > 0 ? merge([
      for shard_key, shard_module in module.shards : {
        "shard_${shard_key}_cos_agent" = shard_module.provides["cos_agent"]
      }
    ]...) : {}
  )
}

output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = merge(
    {
      config_server_client_certificates       = module.config_server.requires["client_certificates"]
      config_server_etcd                      = module.config_server.requires["etcd"]
      config_server_gcs_credentials           = module.config_server.requires["gcs_credentials"]
      config_server_ldap                      = module.config_server.requires["ldap"]
      config_server_ldap_certificate_transfer = module.config_server.requires["ldap_certificate_transfer"]
      config_server_peer_certificates         = module.config_server.requires["peer_certificates"]
      config_server_s3_credentials            = module.config_server.requires["s3_credentials"]
      config_server_vault_kv                  = module.config_server.requires["vault_kv"]
      mongos_client_certificates              = module.mongos.requires["client_certificates"]
      mongos_cluster                          = module.mongos.requires["cluster"]
      mongos_etcd                             = module.mongos.requires["etcd"]
      mongos_ldap                             = module.mongos.requires["ldap"]
      mongos_ldap_certificate_transfer        = module.mongos.requires["ldap_certificate_transfer"]
      mongos_proxy                            = module.mongos.requires["mongos_proxy"]
      mongos_peer_certificates                = module.mongos.requires["peer_certificates"]
    },
    length(module.shards) > 0 ? merge([
      for shard_key, shard_module in module.shards : {
        "shard_${shard_key}_client_certificates" = shard_module.requires["client_certificates"]
        "shard_${shard_key}_etcd"                = shard_module.requires["etcd"]
        "shard_${shard_key}_peer_certificates"   = shard_module.requires["peer_certificates"]
        "shard_${shard_key}_sharding"            = shard_module.requires["sharding"]
        "shard_${shard_key}_vault_kv"            = shard_module.requires["vault_kv"]
      }
    ]...) : {}
  )
}

output "offers" {
  description = "Map of all offer endpoints."
  value = {
    config_server = try({
      kind = "offer"
      url  = juju_offer.config_server_to_shard["offered"].url
    }, null)
  }
}
