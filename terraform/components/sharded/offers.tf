# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 2. OFFERS (cross model)
#--------------------------------------------------------

resource "juju_offer" "config_server_to_shard" {
  for_each = length(local.shards_not_in_config_server_model) > 0 ? { "offered" = true } : {}

  application_name = module.config_server.provides["config_server"].name
  endpoints        = [module.config_server.provides["config_server"].endpoint]
  model_uuid       = module.config_server.application.model_uuid
}
