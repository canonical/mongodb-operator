# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  shards = [
    for app in concat(var.shards != null ? var.shards : []) : app if app != null
  ]

  shards_in_config_server_model = [
    for shard in local.shards :
    shard if shard != null && shard.model_uuid == var.config_server.model_uuid
  ]

  shards_not_in_config_server_model = [
    for shard in local.shards :
    shard if shard != null && shard.model_uuid != var.config_server.model_uuid
  ]

  mongodb_apps = concat([var.config_server], local.shards)

  encryption_at_rest_enabled  = var.vault_kv_offer != null ? true : false
  etcd_rolling_ops_enabled    = var.etcd_offer != null ? true : false
  client_certificates_enabled = var.etcd_offer != null ? true : false
  gcs_credentials_enabled     = var.gcs_credentials_offer != null ? true : false
  ldap_enabled                = var.ldap_offer != null && var.ldap_certificate_transfer_offer != null ? true : false
  peer_certificates_enabled   = var.peer_certificates_offer != null ? true : false
  s3_credentials_enabled      = var.s3_credentials_offer != null ? true : false
}
