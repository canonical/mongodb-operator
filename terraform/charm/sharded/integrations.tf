# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 3. INTEGRATIONS
#--------------------------------------------------------

resource "juju_integration" "mongodb_config_server_same_model_integrations" {
  for_each   = tomap({ for shard in local.shards_in_config_server_model : shard.app_name => shard })
  model_uuid = each.value.model_uuid

  application {
    name     = var.config_server.app_name
    endpoint = "config-server"
  }
  application {
    name     = each.value.app_name
    endpoint = "sharding"
  }

  depends_on = [
    module.mongodb_config_server,
    module.mongodb_shards,
  ]
}

resource "juju_integration" "mongodb_config_server_cross_model_integrations" {
  for_each   = tomap({ for shard in local.shards_not_in_config_server_model : shard.app_name => shard })
  model_uuid = each.value.model_uuid

  application {
    offer_url = juju_offer.mongodb_config_server_offer["offered"].url
  }
  application {
    name     = each.value.app_name
    endpoint = "sharding"
  }

  depends_on = [
    module.mongodb_config_server,
    module.mongodb_shards,
    juju_offer.mongodb_config_server_offer,
  ]
}


resource "juju_integration" "etcd_integration" {
  for_each   = local.etcd_rolling_ops_enabled ? { for app in local.mongodb_apps : app.app_name => app } : {}
  model_uuid = each.value.model_uuid # TODO : do we need this?

  application {
    name      = var.etcd_offer.kind == "endpoint" ? var.etcd_offer.name : null
    endpoint  = var.etcd_offer.kind == "endpoint" ? var.etcd_offer.endpoint : null
    offer_url = var.etcd_offer.kind == "offer" ? var.etcd_offer.url : null
  }

  application {
    name     = each.value.app_name
    endpoint = "etcd"
  }

  depends_on = [
    module.mongodb_config_server,
    module.mongodb_shards,
  ]
}

resource "juju_integration" "client_certificates_integration" {
  for_each   = local.client_certificates_enabled ? { for app in local.mongodb_apps : app.app_name => app } : {}

  application {
    name      = var.client_certificates_offer.kind == "endpoint" ? var.client_certificates_offer.name : null
    endpoint  = var.client_certificates_offer.kind == "endpoint" ? var.client_certificates_offer.endpoint : null
    offer_url = var.client_certificates_offer.kind == "offer" ? var.client_certificates_offer.url : null
  }

  application {
    name     = each.value.app_name
    endpoint = "client-certificates"
  }
}
# TODO: do we need depends on these relations ?
# TODO : verify who needs integration with

resource "juju_integration" "gcs_credentials_integration" {
  count = local.gcs_credentials_enabled ? 1 : 0

  application {
    name      = var.gcs_credentials_offer.kind == "endpoint" ? var.gcs_credentials_offer.name : null
    endpoint  = var.gcs_credentials_offer.kind == "endpoint" ? var.gcs_credentials_offer.endpoint : null
    offer_url = var.gcs_credentials_offer.kind == "offer" ? var.gcs_credentials_offer.url : null
  }

  application {
    name     = var.config_server.app_name
    endpoint = "gcs-credentials"
  }
}

resource "juju_integration" "ldap_integration" {
  count = local.ldap_enabled ? 1 : 0

  application {
    name      = var.ldap_offer.kind == "endpoint" ? var.ldap_offer.name : null
    endpoint  = var.ldap_offer.kind == "endpoint" ? var.ldap_offer.endpoint : null
    offer_url = var.ldap_offer.kind == "offer" ? var.ldap_offer.url : null
  }

  application {
    name     = var.config_server.app_name
    endpoint = "peer-certificates"
  }

}

resource "juju_integration" "ldap_certificate_transfer_integration" {
  count = local.ldap_enabled ? 1 : 0

  application {
    name      = var.ldap_certificate_transfer_offer.kind == "endpoint" ? var.ldap_certificate_transfer_offer.name : null
    endpoint  = var.ldap_certificate_transfer_offer.kind == "endpoint" ? var.ldap_certificate_transfer_offer.endpoint : null
    offer_url = var.ldap_certificate_transfer_offer.kind == "offer" ? var.ldap_certificate_transfer_offer.url : null
  }

  application {
    name     = var.config_server.app_name
    endpoint = "peer-certificates"
  }
}

resource "juju_integration" "peer_certificates_integration" {
  for_each   = local.peer_certificates_enabled ? { for app in local.mongodb_apps : app.app_name => app } : {}


  application {
    name      = var.peer_certificates_offer.kind == "endpoint" ? var.peer_certificates_offer.name : null
    endpoint  = var.peer_certificates_offer.kind == "endpoint" ? var.peer_certificates_offer.endpoint : null
    offer_url = var.peer_certificates_offer.kind == "offer" ? var.peer_certificates_offer.url : null
  }

  application {
    name     = each.value.app_name
    endpoint = "peer-certificates"
  }
}

resource "juju_integration" "s3_credentials_integration" {
  count = local.s3_credentials_enabled ? 1 : 0

  application {
    name      = var.s3_credentials_offer.kind == "endpoint" ? var.s3_credentials_offer.name : null
    endpoint  = var.s3_credentials_offer.kind == "endpoint" ? var.s3_credentials_offer.endpoint : null
    offer_url = var.s3_credentials_offer.kind == "offer" ? var.s3_credentials_offer.url : null
  }

  application {
    name     = var.config_server.app_name
    endpoint = "s3-credentials"
  }
}

resource "juju_integration" "vault_kv_integration" {
  count = local.encryption_at_rest_enabled ? 1 : 0

  application {
    name      = var.vault_kv_offer.kind == "endpoint" ? var.vault_kv_offer.name : null
    endpoint  = var.vault_kv_offer.kind == "endpoint" ? var.vault_kv_offer.endpoint : null
    offer_url = var.vault_kv_offer.kind == "offer" ? var.vault_kv_offer.url : null
  }

  application {
    name     = var.config_server.app_name
    endpoint = "vault-kv"
  }
}
