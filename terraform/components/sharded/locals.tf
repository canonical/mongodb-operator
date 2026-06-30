# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

locals {
  shards = [
    for app in concat(var.shards != null ? var.shards : []) : app if app != null
  ]

  shards_not_in_config_server_model = [
    for shard in local.shards :
    shard if shard != null && shard.model_uuid != var.config_server.model_uuid
  ]
}
