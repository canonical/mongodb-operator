# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  backups_integrator_channel  = var.backups_integrator != null ? coalesce(var.backups_integrator.channel, var.backups_integrator.storage_type == "s3" ? "2/stable" : "1/stable") : null
  client_certificates_enabled = var.client_certificates_integration != null ? true : false
  encryption_at_rest_enabled  = var.vault_kv_integration != null ? true : false
  etcd_rolling_ops_enabled    = var.etcd_integration != null ? true : false
  gcs_credentials_enabled     = try(var.backups_integrator.storage_type == "gcs", false)
  ldap_enabled                = var.ldap_integration != null && var.ldap_certificate_transfer_integration != null ? true : false
  peer_certificates_enabled   = var.peer_certificates_integration != null ? true : false
  s3_credentials_enabled      = try(var.backups_integrator.storage_type == "s3", false)

  shards = [
    for app in coalesce(var.shards, []) : app if app != null
  ]

  mongodb_apps = concat(
    [{ app_name = var.config_server.app_name, model_uuid = var.config_server.model_uuid }],
    [for shard in local.shards : { app_name = shard.app_name, model_uuid = shard.model_uuid }]
  )
  cos_agent_integrations = var.cos_agent_integrations
  cos_agent_apps = [
    for app in local.mongodb_apps :
    app if contains(keys(local.cos_agent_integrations), app.app_name)
  ]
  mongo_apps = concat(
    local.mongodb_apps,
    [{ app_name = var.mongos.app_name, model_uuid = var.config_server.model_uuid }]
  )
  ldap_mongo_apps = [
    { app_name = var.config_server.app_name, model_uuid = var.config_server.model_uuid },
    { app_name = var.mongos.app_name, model_uuid = var.config_server.model_uuid },
  ]

  ldap_integrations = compact([
    var.ldap_integration != null ? "ldap_integration" : "",
    var.ldap_certificate_transfer_integration != null ? "ldap_certificate_transfer_integration" : "",
  ])

  client_certificates_apps = local.client_certificates_enabled ? local.mongo_apps : []

  client_certificates_cross_model_apps = local.client_certificates_enabled ? [
    for app in local.mongo_apps :
    app if app.model_uuid != var.client_certificates_integration.model_uuid
  ] : []

  etcd_apps = local.etcd_rolling_ops_enabled ? local.mongo_apps : []

  etcd_cross_model_apps = local.etcd_rolling_ops_enabled ? [
    for app in local.mongo_apps :
    app if app.model_uuid != var.etcd_integration.model_uuid
  ] : []

  ldap_apps = local.ldap_enabled ? local.ldap_mongo_apps : []

  ldap_cross_model_apps = local.ldap_enabled ? [
    for app in local.ldap_mongo_apps :
    app if app.model_uuid != var.ldap_integration.model_uuid
  ] : []

  ldap_certificate_transfer_apps = local.ldap_enabled ? local.ldap_mongo_apps : []

  ldap_certificate_transfer_cross_model_apps = local.ldap_enabled ? [
    for app in local.ldap_mongo_apps :
    app if app.model_uuid != var.ldap_certificate_transfer_integration.model_uuid
  ] : []

  peer_certificates_apps = local.peer_certificates_enabled ? local.mongo_apps : []

  peer_certificates_cross_model_apps = local.peer_certificates_enabled ? [
    for app in local.mongo_apps :
    app if app.model_uuid != var.peer_certificates_integration.model_uuid
  ] : []

  encryption_at_rest_apps = concat(
    lookup(var.config_server.config, "enable-encryption-at-rest", "false") == "true" ? [
      { app_name = var.config_server.app_name, model_uuid = var.config_server.model_uuid }
    ] : [],
    [
      for shard in local.shards :
      { app_name = shard.app_name, model_uuid = shard.model_uuid }
      if lookup(shard.config, "enable-encryption-at-rest", "false") == "true"
    ]
  )

  vault_kv_apps = local.encryption_at_rest_enabled ? local.encryption_at_rest_apps : []

  vault_kv_cross_model_apps = local.encryption_at_rest_enabled ? [
    for app in local.vault_kv_apps :
    app if app.model_uuid != var.vault_kv_integration.model_uuid
  ] : []

  client_certificates_requires = merge(
    {
      (module.config_and_routing.requires["config_server_client_certificates"].name) = module.config_and_routing.requires["config_server_client_certificates"]
      (module.config_and_routing.requires["mongos_client_certificates"].name)        = module.config_and_routing.requires["mongos_client_certificates"]
    },
    length(local.shards) > 0 ? {
      for shard_key, shard in local.shards :
      shard.app_name => module.shards[shard_key].requires["client_certificates"]
    } : {}
  )

  cos_agent_provides = merge(
    {
      (module.config_and_routing.provides["config_server_cos_agent"].name) = module.config_and_routing.provides["config_server_cos_agent"]
    },
    length(local.shards) > 0 ? {
      for shard_key, shard in local.shards :
      shard.app_name => module.shards[shard_key].provides["cos_agent"]
    } : {}
  )

  etcd_requires = merge(
    {
      (module.config_and_routing.requires["config_server_etcd"].name) = module.config_and_routing.requires["config_server_etcd"]
      (module.config_and_routing.requires["mongos_etcd"].name)        = module.config_and_routing.requires["mongos_etcd"]
    },
    length(local.shards) > 0 ? {
      for shard_key, shard in local.shards :
      shard.app_name => module.shards[shard_key].requires["etcd"]
    } : {}
  )

  ldap_requires = {
    (module.config_and_routing.requires["config_server_ldap"].name) = module.config_and_routing.requires["config_server_ldap"]
    (module.config_and_routing.requires["mongos_ldap"].name)        = module.config_and_routing.requires["mongos_ldap"]
  }

  ldap_certificate_transfer_requires = {
    (module.config_and_routing.requires["config_server_ldap_certificate_transfer"].name) = module.config_and_routing.requires["config_server_ldap_certificate_transfer"]
    (module.config_and_routing.requires["mongos_ldap_certificate_transfer"].name)        = module.config_and_routing.requires["mongos_ldap_certificate_transfer"]
  }

  peer_certificates_requires = merge(
    {
      (module.config_and_routing.requires["config_server_peer_certificates"].name) = module.config_and_routing.requires["config_server_peer_certificates"]
      (module.config_and_routing.requires["mongos_peer_certificates"].name)        = module.config_and_routing.requires["mongos_peer_certificates"]
    },
    length(local.shards) > 0 ? {
      for shard_key, shard in local.shards :
      shard.app_name => module.shards[shard_key].requires["peer_certificates"]
    } : {}
  )

  vault_kv_requires = merge(
    {
      (module.config_and_routing.requires["config_server_vault_kv"].name) = module.config_and_routing.requires["config_server_vault_kv"]
    },
    length(local.shards) > 0 ? {
      for shard_key, shard in local.shards :
      shard.app_name => module.shards[shard_key].requires["vault_kv"]
    } : {}
  )

  model_components = concat(
    [
      {
        key        = "config_server"
        model_uuid = module.config_and_routing.components["config_server"].model_uuid
        value      = module.config_and_routing.components["config_server"]
      },
      {
        key        = "mongos"
        model_uuid = module.config_and_routing.components["mongos"].model_uuid
        value      = module.config_and_routing.components["mongos"]
      },
      {
        key        = "data_integrator"
        model_uuid = module.data_integrator.application.model_uuid
        value      = module.data_integrator.application
      },
    ],
    length(local.shards) > 0 ? [
      for shard_key, shard in local.shards : {
        key        = "shard_${shard_key}"
        model_uuid = shard.model_uuid
        value      = module.shards[shard_key].application
      }
    ] : [],
    local.s3_credentials_enabled ? [
      {
        key        = "s3_integrator"
        model_uuid = module.s3_integrator[0].application.model_uuid
        value      = module.s3_integrator[0].application
      }
    ] : [],
    local.gcs_credentials_enabled ? [
      {
        key        = "gcs_integrator"
        model_uuid = module.gcs_integrator[0].application.model_uuid
        value      = module.gcs_integrator[0].application
      }
    ] : []
  )
}

resource "terraform_data" "deployed_at" {
  input = timestamp()

  lifecycle {
    ignore_changes = [input]
  }
}
