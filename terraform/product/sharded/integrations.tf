# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# 3. Integrations
#--------------------------------------------------------

resource "juju_integration" "client_certificates_same_model" {
  for_each = (
    local.client_certificates_enabled && local.client_certificates_has_endpoint
    ? local.client_certificates_same_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    name     = var.client_certificates_offer.name
    endpoint = var.client_certificates_offer.endpoint
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  depends_on = [
    module.config_server,
    module.shards,
    juju_application.mongos,
  ]
}

resource "juju_integration" "client_certificates_cross_model" {
  for_each = (
    local.client_certificates_enabled
    ? local.client_certificates_cross_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    offer_url = var.client_certificates_offer.url
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  lifecycle {
    precondition {
      condition     = var.client_certificates_offer.url != null
      error_message = "client_certificates_offer.url must be set when MongoDB targets are in a different model from the client certificates provider."
    }
  }

  depends_on = [
    module.config_server,
    module.shards,
    juju_application.mongos,
  ]
}

resource "juju_integration" "peer_certificates_same_model" {
  for_each = (
    local.peer_certificates_enabled && local.peer_certificates_has_endpoint
    ? local.peer_certificates_same_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    name     = var.peer_certificates_offer.name
    endpoint = var.peer_certificates_offer.endpoint
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  depends_on = [
    module.config_server,
    module.shards,
    juju_application.mongos,
  ]
}

resource "juju_integration" "peer_certificates_cross_model" {
  for_each = (
    local.peer_certificates_enabled
    ? local.peer_certificates_cross_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    offer_url = var.peer_certificates_offer.url
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  lifecycle {
    precondition {
      condition     = var.peer_certificates_offer.url != null
      error_message = "peer_certificates_offer.url must be set when MongoDB targets are in a different model from the peer certificates provider."
    }
  }

  depends_on = [
    module.config_server,
    module.shards,
    juju_application.mongos,
  ]
}

resource "juju_integration" "etcd_same_model" {
  for_each = (
    local.etcd_rolling_ops_enabled && local.etcd_has_endpoint
    ? local.etcd_same_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    name     = var.etcd_offer.name
    endpoint = var.etcd_offer.endpoint
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  depends_on = [
    module.config_server,
    module.shards,
  ]
}

resource "juju_integration" "etcd_cross_model" {
  for_each = (
    local.etcd_rolling_ops_enabled
    ? local.etcd_cross_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    offer_url = var.etcd_offer.url
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  lifecycle {
    precondition {
      condition     = var.etcd_offer.url != null
      error_message = "etcd_offer.url must be set when MongoDB targets are in a different model from the etcd provider."
    }
  }

  depends_on = [
    module.config_server,
    module.shards,
  ]
}

resource "juju_integration" "vault_kv_same_model" {
  for_each = (
    local.encryption_at_rest_enabled && local.vault_kv_has_endpoint
    ? local.vault_kv_same_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    name     = var.vault_kv_offer.name
    endpoint = var.vault_kv_offer.endpoint
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  depends_on = [
    module.config_server,
    module.shards,
  ]
}

resource "juju_integration" "vault_kv_cross_model" {
  for_each = (
    local.encryption_at_rest_enabled
    ? local.vault_kv_cross_model_targets
    : {}
  )

  model_uuid = each.value.model_uuid

  application {
    offer_url = var.vault_kv_offer.url
  }

  application {
    name     = each.value.app_name
    endpoint = each.value.endpoint
  }

  lifecycle {
    precondition {
      condition     = var.vault_kv_offer.url != null
      error_message = "vault_kv_offer.url must be set when MongoDB targets are in a different model from the Vault KV provider."
    }
  }

  depends_on = [
    module.config_server,
    module.shards,
  ]
}

resource "juju_integration" "cos_agent" {
  count      = local.cos_agent_enabled ? 1 : 0
  model_uuid = module.config_server.application.model_uuid

  application {
    name     = var.cos_agent_offer.name
    endpoint = var.cos_agent_offer.endpoint
  }

  application {
    name     = module.config_server.application.name
    endpoint = module.config_server.provides["cos_agent"]
  }

  depends_on = [module.config_server]
}


resource "juju_integration" "mongodb_ldap" {
  count      = local.ldap_enabled ? 1 : 0
  model_uuid = module.config_server.application.model_uuid

  application {
    name      = var.ldap_offer.kind == "endpoint" ? var.ldap_offer.name : null
    endpoint  = var.ldap_offer.kind == "endpoint" ? var.ldap_offer.endpoint : null
    offer_url = var.ldap_offer.kind == "offer" ? var.ldap_offer.url : null
  }

  application {
    name     = module.config_server.application.name
    endpoint = module.config_server.requires["ldap"]
  }

  depends_on = [module.config_server]
}

resource "juju_integration" "mongodb_ldap_certificate_transfer" {
  count      = local.ldap_enabled ? 1 : 0
  model_uuid = module.config_server.application.model_uuid

  application {
    name      = var.ldap_certificate_transfer_offer.kind == "endpoint" ? var.ldap_certificate_transfer_offer.name : null
    endpoint  = var.ldap_certificate_transfer_offer.kind == "endpoint" ? var.ldap_certificate_transfer_offer.endpoint : null
    offer_url = var.ldap_certificate_transfer_offer.kind == "offer" ? var.ldap_certificate_transfer_offer.url : null
  }

  application {
    name     = module.config_server.application.name
    endpoint = module.config_server.requires["ldap_certificate_transfer"]
  }

  depends_on = [module.config_server]
}

resource "juju_integration" "mongos_ldap" {
  count      = local.ldap_enabled ? 1 : 0
  model_uuid = module.mongos.application.model_uuid

  application {
    name      = var.ldap_offer.kind == "endpoint" ? var.ldap_offer.name : null
    endpoint  = var.ldap_offer.kind == "endpoint" ? var.ldap_offer.endpoint : null
    offer_url = var.ldap_offer.kind == "offer" ? var.ldap_offer.url : null
  }

  application {
    name     = module.mongos.application.name
    endpoint = module.mongos.requires["ldap"]
  }

  depends_on = [module.mongos]
}

resource "juju_integration" "mongos_ldap_certificate_transfer" {
  count      = local.ldap_enabled ? 1 : 0
  model_uuid = module.mongos.application.model_uuid

  application {
    name      = var.ldap_certificate_transfer_offer.kind == "endpoint" ? var.ldap_certificate_transfer_offer.name : null
    endpoint  = var.ldap_certificate_transfer_offer.kind == "endpoint" ? var.ldap_certificate_transfer_offer.endpoint : null
    offer_url = var.ldap_certificate_transfer_offer.kind == "offer" ? var.ldap_certificate_transfer_offer.url : null
  }

  application {
    name     = module.mongos.application.name
    endpoint = module.mongos.requires["ldap_certificate_transfer"]
  }

  depends_on = [module.mongos]
}

# Integrator relations

resource "juju_integration" "mongos_client" {
  model_uuid = var.mongos.model_uuid

  application {
    name     = module.mongos.application.name
    endpoint = module.mongos.requires["mongos_proxy"]
  }

  application {
    name      = var.data_integrator.model_uuid == module.mongodb.application.model_uuid ? var.data_integrator.app_name : null
    endpoint  = var.data_integrator.model_uuid == module.mongodb.application.model_uuid ? "mongos" : null
    offer_url = try(juju_offer.data_integrator["offered"].url, null)
  }

  depends_on = [
    module.mongos,
    juju_application.data_integrator,
  ]
}

resource "juju_integration" "mongodb_s3" {
  for_each = var.s3_integrator != null ? { "integrated" = var.s3_integrator } : {}

  model_uuid = module.config_server.application.model_uuid

  application {
    name     = module.config_server.application.name
    endpoint = module.config_server.requires["s3_credentials"]
  }
  application {
    name      = each.value.model_uuid == module.config_server.application.model_uuid ? each.value.app_name : null
    endpoint  = each.value.model_uuid == module.config_server.application.model_uuid ? "s3-credentials" : null
    offer_url = try(juju_offer.s3_integrator["offered"].url, null)
  }
  depends_on = [
    module.config_server,
    juju_application.s3_integrator["deployed"],
  ]
}

resource "juju_integration" "mongodb_gcs" {
  for_each = var.gcs_integrator != null ? { "integrated" = var.gcs_integrator } : {}

  model_uuid = module.config_server.application.model_uuid

  application {
    name     = module.config_server.application.name
    endpoint = module.config_server.requires["gcs_credentials"]
  }
  application {
    name      = each.value.model_uuid == module.config_server.application.model_uuid ? each.value.app_name : null
    endpoint  = each.value.model_uuid == module.config_server.application.model_uuid ? "gcs-credentials" : null
    offer_url = try(juju_offer.gcs_integrator["offered"].url, null)
  }
  depends_on = [
    module.config_server,
    juju_application.gcs_integrator["deployed"],
  ]
}




## Same model integrations

resource "juju_integration" "mongodb_grafana_agent_integration" {
  count      = length(local.mongodb_apps)
  model_uuid = local.mongo_apps[count.index].model_uuid

  application {
    name = local.mongo_apps[count.index].app_name
  }
  application {
    name = "grafana-agent-${local.mongo_apps[count.index].app_name}"
  }
  depends_on = [
    module.mongodb,
    juju_application.grafana_agent,
  ]
}

resource "juju_integration" "mongos_data_integrator_same_model_integration" {
  application {
    name = var.data_integrator.app_name
  }
  application {
    name = var.mongos.app_name
  }
  depends_on = [
    juju_application.mongos,
    juju_application.data_integrator,
  ]
  model_uuid = var.data_integrator.model_uuid
}

resource "juju_integration" "config_server_mongos_same_model_integration" {
  application {
    name = var.config_server.app_name
  }
  application {
    name = var.mongos.app_name
  }
  depends_on = [
    module.mongodb,
    juju_integration.mongos_data_integrator_same_model_integration,
  ]
  model_uuid = var.mongos.model_uuid
}

resource "juju_integration" "tls_peer_mongo_same_model_integration" {
  count = length(local.tls_same_model_mongo_apps)

  model_uuid = local.tls_same_model_mongo_apps[count.index].model_uuid
  application {
    name     = local.tls_same_model_mongo_apps[count.index].app_name
    endpoint = "peer-certificates"
  }
  application {
    name     = var.self_signed_certificates.app_name
    endpoint = "certificates"
  }
  depends_on = [
    module.mongodb,
    juju_application.self-signed-certificates["deployed"],
  ]
}

resource "juju_integration" "tls_client_mongo_same_model_integration" {
  count = length(local.tls_same_model_mongo_apps)

  model_uuid = local.tls_same_model_mongo_apps[count.index].model_uuid
  application {
    name     = local.tls_same_model_mongo_apps[count.index].app_name
    endpoint = "client-certificates"
  }
  application {
    name     = var.self_signed_certificates.app_name
    endpoint = "certificates"
  }
  depends_on = [
    module.mongodb,
    juju_application.self-signed-certificates["deployed"],
  ]
}

resource "juju_integration" "s3_config_server_same_model_integration" {
  for_each = var.s3_integrator.model_uuid == var.config_server.model_uuid ? { "integrated" = true } : {}

  application {
    name = var.config_server.app_name
  }
  application {
    name = var.s3_integrator.app_name
  }
  depends_on = [
    module.mongodb,
    juju_application.s3_integrator,
  ]
  model_uuid = var.config_server.model_uuid
}

#--------------------------------------------------------
## Cross model integrations

resource "juju_integration" "config_server_mongos_cross_model_integration" {
  for_each = var.mongos.model_uuid != var.config_server.model_uuid ? { "integrated" = true } : {}

  application {
    offer_url = juju_offer.config_server_mongos_offer["offered"].url
  }
  application {
    name     = var.mongos.app_name
    endpoint = "cluster"
  }
  depends_on = [
    juju_application.mongos,
    juju_offer.config_server_mongos_offer,
  ]
  model_uuid = var.mongos.model_uuid
}

resource "juju_integration" "tls_peer_mongo_cross_model_integration" {
  count = length(local.tls_cross_model_mongo_apps)

  model_uuid = local.tls_cross_model_mongo_apps[count.index].model_uuid

  application {
    offer_url = juju_offer.tls_provider_offer["offered"].url
  }
  application {
    name     = local.tls_cross_model_mongo_apps[count.index].app_name
    endpoint = "peer-certificates"
  }
  depends_on = [
    module.mongodb,
    juju_offer.tls_provider_offer,
  ]
}

resource "juju_integration" "tls_client_mongo_cross_model_integration" {
  count = length(local.tls_cross_model_mongo_apps)

  model_uuid = local.tls_cross_model_mongo_apps[count.index].model_uuid

  application {
    offer_url = juju_offer.tls_provider_offer["offered"].url
  }
  application {
    name     = local.tls_cross_model_mongo_apps[count.index].app_name
    endpoint = "client-certificates"
  }
  depends_on = [
    module.mongodb,
    juju_offer.tls_provider_offer,
  ]
}

resource "juju_integration" "s3_config_server_cross_model_integration" {
  for_each = var.s3_integrator.model_uuid != var.config_server.model_uuid ? { "integrated" = true } : {}

  application {
    offer_url = juju_offer.s3_integrator_offer["offered"].url
  }
  application {
    name     = var.config_server.app_name
    endpoint = "s3-credentials"
  }
  depends_on = [
    module.mongodb,
    juju_offer.s3_integrator_offer,
  ]
  model_uuid = var.config_server.model_uuid
}
