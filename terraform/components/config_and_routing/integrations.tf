# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 2. INTEGRATIONS
#--------------------------------------------------------

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
