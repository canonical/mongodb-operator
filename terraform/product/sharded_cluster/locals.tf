# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  client_certificates_enabled = var.client_certificates_integration != null ? true : false
  encryption_at_rest_enabled  = var.vault_kv_integration != null ? true : false
  etcd_rolling_ops_enabled    = var.etcd_integration != null ? true : false
  gcs_credentials_enabled     = var.gcs_integrator != null ? true : false
  ldap_enabled                = var.ldap_integration != null && var.ldap_certificate_transfer_integration != null ? true : false
  peer_certificates_enabled   = var.peer_certificates_integration != null ? true : false
  s3_credentials_enabled      = var.s3_integrator != null ? true : false

  mongodb_apps = concat(
    [{ app_name = var.config_server.app_name, model_uuid = var.config_server.model_uuid }],
    var.shards != null ? [for shard in var.shards : { app_name = shard.app_name, model_uuid = shard.model_uuid }] : []
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

  backup_integrations = compact([
    var.s3_integrator != null ? "s3_integrator" : "",
    var.gcs_integrator != null ? "gcs_integrator" : "",
  ])

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

  vault_kv_apps = local.encryption_at_rest_enabled ? local.mongodb_apps : []

  vault_kv_cross_model_apps = local.encryption_at_rest_enabled ? [
    for app in local.mongodb_apps :
    app if app.model_uuid != var.vault_kv_integration.model_uuid
  ] : []

  client_certificates_requires = merge(
    {
      (module.cluster.requires["config_server_client_certificates"].name) = module.cluster.requires["config_server_client_certificates"]
      (module.cluster.requires["mongos_client_certificates"].name)        = module.cluster.requires["mongos_client_certificates"]
    },
    var.shards != null ? {
      for shard_key, shard in var.shards :
      shard.app_name => module.cluster.requires["shard_${shard_key}_client_certificates"]
    } : {}
  )

  cos_agent_provides = merge(
    {
      (module.cluster.provides["config_server_cos_agent"].name) = module.cluster.provides["config_server_cos_agent"]
    },
    var.shards != null ? {
      for shard_key, shard in var.shards :
      shard.app_name => module.cluster.provides["shard_${shard_key}_cos_agent"]
    } : {}
  )

  etcd_requires = merge(
    {
      (module.cluster.requires["config_server_etcd"].name) = module.cluster.requires["config_server_etcd"]
      (module.cluster.requires["mongos_etcd"].name)        = module.cluster.requires["mongos_etcd"]
    },
    var.shards != null ? {
      for shard_key, shard in var.shards :
      shard.app_name => module.cluster.requires["shard_${shard_key}_etcd"]
    } : {}
  )

  ldap_requires = {
    (module.cluster.requires["config_server_ldap"].name) = module.cluster.requires["config_server_ldap"]
    (module.cluster.requires["mongos_ldap"].name)        = module.cluster.requires["mongos_ldap"]
  }

  ldap_certificate_transfer_requires = {
    (module.cluster.requires["config_server_ldap_certificate_transfer"].name) = module.cluster.requires["config_server_ldap_certificate_transfer"]
    (module.cluster.requires["mongos_ldap_certificate_transfer"].name)        = module.cluster.requires["mongos_ldap_certificate_transfer"]
  }

  peer_certificates_requires = merge(
    {
      (module.cluster.requires["config_server_peer_certificates"].name) = module.cluster.requires["config_server_peer_certificates"]
      (module.cluster.requires["mongos_peer_certificates"].name)        = module.cluster.requires["mongos_peer_certificates"]
    },
    var.shards != null ? {
      for shard_key, shard in var.shards :
      shard.app_name => module.cluster.requires["shard_${shard_key}_peer_certificates"]
    } : {}
  )

  vault_kv_requires = merge(
    {
      (module.cluster.requires["config_server_vault_kv"].name) = module.cluster.requires["config_server_vault_kv"]
    },
    var.shards != null ? {
      for shard_key, shard in var.shards :
      shard.app_name => module.cluster.requires["shard_${shard_key}_vault_kv"]
    } : {}
  )

  model_components = concat(
    [
      {
        key        = "config_server"
        model_uuid = module.cluster.components["config_server"].model_uuid
        value      = module.cluster.components["config_server"]
      },
      {
        key        = "mongos"
        model_uuid = module.cluster.components["mongos"].model_uuid
        value      = module.cluster.components["mongos"]
      },
      {
        key        = "data_integrator"
        model_uuid = juju_application.data_integrator.model_uuid
        value      = juju_application.data_integrator
      },
    ],
    var.shards != null ? [
      for shard_key, shard in var.shards : {
        key        = "shard_${shard_key}"
        model_uuid = shard.model_uuid
        value      = module.cluster.components["shards"][shard_key]
      }
    ] : [],
    var.s3_integrator != null ? [
      {
        key        = "s3_integrator"
        model_uuid = module.s3_integrator[0].application.model_uuid
        value      = module.s3_integrator[0].application
      }
    ] : [],
    var.gcs_integrator != null ? [
      {
        key        = "gcs_integrator"
        model_uuid = juju_application.gcs_integrator["deployed"].model_uuid
        value      = juju_application.gcs_integrator["deployed"]
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
