# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# 3. Integrations
#--------------------------------------------------------

resource "juju_integration" "certificates" {
  count      = local.certificates_enabled ? 1 : 0
  model_uuid = module.mongodb.application.model_uuid

  application {
    name      = var.certificates_integration.kind == "endpoint" ? var.certificates_integration.name : null
    endpoint  = var.certificates_integration.kind == "endpoint" ? var.certificates_integration.endpoint : null
    offer_url = var.certificates_integration.kind == "offer" ? var.certificates_integration.url : null
  }

  application {
    name     = module.mongodb.requires["certificates"].name
    endpoint = module.mongodb.requires["certificates"].endpoint
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
  for_each = local.s3_integrator_enabled ? { "integrated" = true } : {}

  model_uuid = module.mongodb.application.model_uuid

  application {
    name     = module.mongodb.requires["s3_credentials"].name
    endpoint = module.mongodb.requires["s3_credentials"].endpoint
  }
  application {
    name      = var.backups_integrator.model_uuid == module.mongodb.application.model_uuid ? module.s3_integrator[0].provides.s3_credentials.name : null
    endpoint  = var.backups_integrator.model_uuid == module.mongodb.application.model_uuid ? module.s3_integrator[0].provides.s3_credentials.endpoint : null
    offer_url = var.backups_integrator.model_uuid != module.mongodb.application.model_uuid ? module.s3_integrator[0].offers.s3_credentials.url : null
  }
  depends_on = [
    module.mongodb,
    module.s3_integrator,
  ]
}
