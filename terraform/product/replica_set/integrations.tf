# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# 3. Integrations
#--------------------------------------------------------

resource "juju_integration" "client_certificates" {
  count      = local.client_certificates_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name      = var.client_certificates_integration.kind == "endpoint" ? var.client_certificates_integration.name : null
    endpoint  = var.client_certificates_integration.kind == "endpoint" ? var.client_certificates_integration.endpoint : null
    offer_url = var.client_certificates_integration.kind == "offer" ? var.client_certificates_integration.url : null
  }

  application {
    name     = module.mongodb.requires["client_certificates"].name
    endpoint = module.mongodb.requires["client_certificates"].endpoint
  }

  depends_on = [module.mongodb]
}

resource "juju_integration" "cos_agent" {
  count      = local.cos_agent_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name     = var.cos_agent_integration.name
    endpoint = var.cos_agent_integration.endpoint
  }

  application {
    name     = module.mongodb.provides["cos_agent"].name
    endpoint = module.mongodb.provides["cos_agent"].endpoint
  }

  depends_on = [module.mongodb]
}

resource "juju_integration" "etcd" {
  count      = local.etcd_rolling_ops_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name      = var.etcd_integration.kind == "endpoint" ? var.etcd_integration.name : null
    endpoint  = var.etcd_integration.kind == "endpoint" ? var.etcd_integration.endpoint : null
    offer_url = var.etcd_integration.kind == "offer" ? var.etcd_integration.url : null
  }

  application {
    name     = module.mongodb.requires["etcd"].name
    endpoint = module.mongodb.requires["etcd"].endpoint
  }

  depends_on = [module.mongodb]
}

resource "juju_integration" "ldap" {
  count      = local.ldap_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name      = var.ldap_integration.kind == "endpoint" ? var.ldap_integration.name : null
    endpoint  = var.ldap_integration.kind == "endpoint" ? var.ldap_integration.endpoint : null
    offer_url = var.ldap_integration.kind == "offer" ? var.ldap_integration.url : null
  }

  application {
    name     = module.mongodb.requires["ldap"].name
    endpoint = module.mongodb.requires["ldap"].endpoint
  }

  depends_on = [module.mongodb]
}

resource "juju_integration" "ldap_certificate_transfer" {
  count      = local.ldap_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name      = var.ldap_certificate_transfer_integration.kind == "endpoint" ? var.ldap_certificate_transfer_integration.name : null
    endpoint  = var.ldap_certificate_transfer_integration.kind == "endpoint" ? var.ldap_certificate_transfer_integration.endpoint : null
    offer_url = var.ldap_certificate_transfer_integration.kind == "offer" ? var.ldap_certificate_transfer_integration.url : null
  }

  application {
    name     = module.mongodb.requires["ldap_certificate_transfer"].name
    endpoint = module.mongodb.requires["ldap_certificate_transfer"].endpoint
  }

  depends_on = [module.mongodb]
}

resource "juju_integration" "peer_certificates" {
  count      = local.peer_certificates_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name      = var.peer_certificates_integration.kind == "endpoint" ? var.peer_certificates_integration.name : null
    endpoint  = var.peer_certificates_integration.kind == "endpoint" ? var.peer_certificates_integration.endpoint : null
    offer_url = var.peer_certificates_integration.kind == "offer" ? var.peer_certificates_integration.url : null
  }

  application {
    name     = module.mongodb.requires["peer_certificates"].name
    endpoint = module.mongodb.requires["peer_certificates"].endpoint
  }

  depends_on = [module.mongodb]
}

resource "juju_integration" "vault_kv" {
  count      = local.encryption_at_rest_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name      = var.vault_kv_integration.kind == "endpoint" ? var.vault_kv_integration.name : null
    endpoint  = var.vault_kv_integration.kind == "endpoint" ? var.vault_kv_integration.endpoint : null
    offer_url = var.vault_kv_integration.kind == "offer" ? var.vault_kv_integration.url : null
  }

  application {
    name     = module.mongodb.requires["vault_kv"].name
    endpoint = module.mongodb.requires["vault_kv"].endpoint
  }

  depends_on = [module.mongodb]
}

# Integrator relations

resource "juju_integration" "mongodb_data" {
  model_uuid = var.data_integrator.model_uuid

  application {
    name      = var.data_integrator.model_uuid == module.mongodb.application.model_uuid ? module.mongodb.provides["database"].name : null
    endpoint  = var.data_integrator.model_uuid == module.mongodb.application.model_uuid ? module.mongodb.provides["database"].endpoint : null
    offer_url = try(juju_offer.mongodb_client["offered"].url, null)
  }
  application {
    name     = module.data_integrator.application.name
    endpoint = "mongodb"
  }
  depends_on = [
    module.mongodb,
    module.data_integrator,
  ]
}

resource "juju_integration" "mongodb_s3" {
  for_each = var.s3_integrator != null ? { "integrated" = true } : {}

  model_uuid = module.mongodb.application.model_uuid

  application {
    name     = module.mongodb.requires["s3_credentials"].name
    endpoint = module.mongodb.requires["s3_credentials"].endpoint
  }
  application {
    name      = var.s3_integrator.model_uuid == module.mongodb.application.model_uuid ? module.s3_integrator[0].provides.s3_credentials.name : null
    endpoint  = var.s3_integrator.model_uuid == module.mongodb.application.model_uuid ? module.s3_integrator[0].provides.s3_credentials.endpoint : null
    offer_url = var.s3_integrator.model_uuid != module.mongodb.application.model_uuid ? module.s3_integrator[0].offers.s3_credentials.url : null
  }
  depends_on = [
    module.mongodb,
    module.s3_integrator,
  ]
}

resource "juju_integration" "mongodb_gcs" {
  for_each = var.gcs_integrator != null ? { "integrated" = true } : {}

  model_uuid = module.mongodb.application.model_uuid

  application {
    name     = module.mongodb.requires["gcs_credentials"].name
    endpoint = module.mongodb.requires["gcs_credentials"].endpoint
  }
  application {
    name      = var.gcs_integrator.model_uuid == module.mongodb.application.model_uuid ? module.gcs_integrator[0].provides.gcs_credentials.name : null
    endpoint  = var.gcs_integrator.model_uuid == module.mongodb.application.model_uuid ? module.gcs_integrator[0].provides.gcs_credentials.endpoint : null
    offer_url = var.gcs_integrator.model_uuid != module.mongodb.application.model_uuid ? module.gcs_integrator[0].offers.gcs_credentials.url : null
  }
  depends_on = [
    module.mongodb,
    module.gcs_integrator,
  ]
}
