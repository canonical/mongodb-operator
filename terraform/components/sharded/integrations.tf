# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 3. INTEGRATIONS
#--------------------------------------------------------

resource "juju_integration" "config_server_shards" {
  for_each   = tomap({ for shard_key, shard in local.shards : shard_key => shard })
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == module.config_server.application.model_uuid ? module.config_server.provides["config_server"].name : null
    endpoint  = each.value.model_uuid == module.config_server.application.model_uuid ? module.config_server.provides["config_server"].endpoint : null
    offer_url = each.value.model_uuid != module.config_server.application.model_uuid ? juju_offer.config_server_to_shard["offered"].url : null
  }
  application {
    name     = module.shards[each.key].requires["sharding"].name
    endpoint = module.shards[each.key].requires["sharding"].endpoint
  }

  depends_on = [
    module.config_server,
    module.shards,
    juju_offer.config_server_to_shard,
  ]
}

resource "juju_integration" "config_server_mongos" {
  model_uuid = module.config_server.application.model_uuid

  application {
    name     = module.config_server.provides["cluster"].name
    endpoint = module.config_server.provides["cluster"].endpoint
  }

  application {
    name     = module.mongos.requires["cluster"].name
    endpoint = module.mongos.requires["cluster"].endpoint
  }

  depends_on = [
    module.config_server,
    module.mongos
  ]
}
