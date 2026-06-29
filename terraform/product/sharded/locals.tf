# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  cos_agent_enabled           = var.cos_agent_offer != null ? true : false
  encryption_at_rest_enabled  = var.vault_kv_offer != null ? true : false
  etcd_rolling_ops_enabled    = var.etcd_offer != null ? true : false
  client_certificates_enabled = var.client_certificates_offer != null ? true : false
  ldap_enabled                = var.ldap_offer != null && var.ldap_certificate_transfer_offer != null ? true : false
  peer_certificates_enabled   = var.peer_certificates_offer != null ? true : false

  backup_integrations = compact([
    var.s3_integrator != null ? "s3_integrator" : "",
    var.gcs_integrator != null ? "gcs_integrator" : "",
  ])

  ldap_integrations = compact([
    var.ldap_offer != null ? "ldap_offer" : "",
    var.ldap_certificate_transfer_offer != null ? "ldap_certificate_transfer_offer" : "",
  ])

  shards = [
    for app in var.shards : app if app != null
  ]

  shards_in_config_server_model = [
    for shard in local.shards :
    shard if shard != null && shard.model_uuid == var.config_server.model_uuid
  ]

  shards_not_in_config_server_model = [
    for shard in local.shards :
    shard if shard != null && shard.model_uuid != var.config_server.model_uuid
  ]

  mongodb_apps = concat([var.config_server], local.shards, [var.mongos])

  client_certificates_targets = merge(
    {
      config_server = {
        app_name   = module.config_server.application.name
        endpoint   = module.config_server.requires["client_certificates"]
        model_uuid = module.config_server.application.model_uuid
      }
      mongos = {
        app_name   = juju_application.mongos.name
        endpoint   = "client-certificates"
        model_uuid = juju_application.mongos.model_uuid
      }
    },
    {
      for shard_key, shard in module.shards :
      "shard_${shard_key}" => {
        app_name   = shard.application.name
        endpoint   = shard.requires["client_certificates"]
        model_uuid = shard.application.model_uuid
      }
    }
  )

  client_certificates_has_endpoint = (
    try(var.client_certificates_offer.name, null) != null
    && try(var.client_certificates_offer.endpoint, null) != null
    && try(var.client_certificates_offer.model_uuid, null) != null
  )
  client_certificates_provider_model_uuid = try(var.client_certificates_offer.model_uuid, null)

  client_certificates_same_model_targets = {
    for target_key, target in local.client_certificates_targets :
    target_key => target if local.client_certificates_has_endpoint && target.model_uuid == local.client_certificates_provider_model_uuid
  }

  client_certificates_cross_model_targets = {
    for target_key, target in local.client_certificates_targets :
    target_key => target if !local.client_certificates_has_endpoint || target.model_uuid != local.client_certificates_provider_model_uuid
  }

  peer_certificates_targets = merge(
    {
      config_server = {
        app_name   = module.config_server.application.name
        endpoint   = module.config_server.requires["peer_certificates"]
        model_uuid = module.config_server.application.model_uuid
      }
      mongos = {
        app_name   = juju_application.mongos.name
        endpoint   = "peer-certificates"
        model_uuid = juju_application.mongos.model_uuid
      }
    },
    {
      for shard_key, shard in module.shards :
      "shard_${shard_key}" => {
        app_name   = shard.application.name
        endpoint   = shard.requires["peer_certificates"]
        model_uuid = shard.application.model_uuid
      }
    }
  )

  peer_certificates_has_endpoint = (
    try(var.peer_certificates_offer.name, null) != null
    && try(var.peer_certificates_offer.endpoint, null) != null
    && try(var.peer_certificates_offer.model_uuid, null) != null
  )
  peer_certificates_provider_model_uuid = try(var.peer_certificates_offer.model_uuid, null)

  peer_certificates_same_model_targets = {
    for target_key, target in local.peer_certificates_targets :
    target_key => target if local.peer_certificates_has_endpoint && target.model_uuid == local.peer_certificates_provider_model_uuid
  }

  peer_certificates_cross_model_targets = {
    for target_key, target in local.peer_certificates_targets :
    target_key => target if !local.peer_certificates_has_endpoint || target.model_uuid != local.peer_certificates_provider_model_uuid
  }

  etcd_targets = merge(
    {
      config_server = {
        app_name   = module.config_server.application.name
        endpoint   = module.config_server.requires["etcd"]
        model_uuid = module.config_server.application.model_uuid
      }
    },
    {
      for shard_key, shard in module.shards :
      "shard_${shard_key}" => {
        app_name   = shard.application.name
        endpoint   = shard.requires["etcd"]
        model_uuid = shard.application.model_uuid
      }
    }
  )

  etcd_has_endpoint = (
    try(var.etcd_offer.name, null) != null
    && try(var.etcd_offer.endpoint, null) != null
    && try(var.etcd_offer.model_uuid, null) != null
  )
  etcd_provider_model_uuid = try(var.etcd_offer.model_uuid, null)

  etcd_same_model_targets = {
    for target_key, target in local.etcd_targets :
    target_key => target if local.etcd_has_endpoint && target.model_uuid == local.etcd_provider_model_uuid
  }

  etcd_cross_model_targets = {
    for target_key, target in local.etcd_targets :
    target_key => target if !local.etcd_has_endpoint || target.model_uuid != local.etcd_provider_model_uuid
  }

  vault_kv_targets = merge(
    {
      config_server = {
        app_name   = module.config_server.application.name
        endpoint   = module.config_server.requires["vault_kv"]
        model_uuid = module.config_server.application.model_uuid
      }
    },
    {
      for shard_key, shard in module.shards :
      "shard_${shard_key}" => {
        app_name   = shard.application.name
        endpoint   = shard.requires["vault_kv"]
        model_uuid = shard.application.model_uuid
      }
    }
  )

  vault_kv_has_endpoint = (
    try(var.vault_kv_offer.name, null) != null
    && try(var.vault_kv_offer.endpoint, null) != null
    && try(var.vault_kv_offer.model_uuid, null) != null
  )
  vault_kv_provider_model_uuid = try(var.vault_kv_offer.model_uuid, null)

  vault_kv_same_model_targets = {
    for target_key, target in local.vault_kv_targets :
    target_key => target if local.vault_kv_has_endpoint && target.model_uuid == local.vault_kv_provider_model_uuid
  }

  vault_kv_cross_model_targets = {
    for target_key, target in local.vault_kv_targets :
    target_key => target if !local.vault_kv_has_endpoint || target.model_uuid != local.vault_kv_provider_model_uuid
  }
}
