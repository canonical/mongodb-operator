# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# 3. Integrations
#--------------------------------------------------------

# Shards
resource "juju_integration" "config_server_shards" {
  for_each   = tomap({ for shard_key, shard in local.shards : shard_key => shard })
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == module.config_and_routing.components["config_server"].model_uuid ? module.config_and_routing.provides["config_server"].name : null
    endpoint  = each.value.model_uuid == module.config_and_routing.components["config_server"].model_uuid ? module.config_and_routing.provides["config_server"].endpoint : null
    offer_url = each.value.model_uuid != module.config_and_routing.components["config_server"].model_uuid ? module.config_and_routing.offers["config_server"].url : null
  }

  application {
    name     = module.shards[each.key].requires["sharding"].name
    endpoint = module.shards[each.key].requires["sharding"].endpoint
  }

  depends_on = [
    module.config_and_routing,
    module.shards,
  ]
}

# Integrators
resource "juju_integration" "mongos_client" {
  model_uuid = module.config_and_routing.components["mongos"].model_uuid

  application {
    name     = module.config_and_routing.requires["mongos_proxy"].name
    endpoint = module.config_and_routing.requires["mongos_proxy"].endpoint
  }

  application {
    name     = module.data_integrator.application.name
    endpoint = "mongos"
  }

  depends_on = [
    module.config_and_routing,
    module.data_integrator,
  ]
}

resource "juju_integration" "s3_credentials" {
  for_each   = local.s3_credentials_enabled ? { "integrated" = true } : {}
  model_uuid = module.config_and_routing.components["config_server"].model_uuid

  application {
    name     = module.config_and_routing.requires["config_server_s3_credentials"].name
    endpoint = module.config_and_routing.requires["config_server_s3_credentials"].endpoint
  }

  application {
    name      = var.backups_integrator.model_uuid == module.config_and_routing.components["config_server"].model_uuid ? module.s3_integrator[0].provides.s3_credentials.name : null
    endpoint  = var.backups_integrator.model_uuid == module.config_and_routing.components["config_server"].model_uuid ? module.s3_integrator[0].provides.s3_credentials.endpoint : null
    offer_url = var.backups_integrator.model_uuid != module.config_and_routing.components["config_server"].model_uuid ? module.s3_integrator[0].offers.s3_credentials.url : null
  }

  depends_on = [
    module.config_and_routing,
    module.s3_integrator,
  ]
}

# Other apps
resource "juju_integration" "cos_agent" {
  for_each   = { for app in local.cos_agent_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name     = local.cos_agent_integrations[each.key].name
    endpoint = local.cos_agent_integrations[each.key].endpoint
  }

  application {
    name     = local.cos_agent_provides[each.key].name
    endpoint = local.cos_agent_provides[each.key].endpoint
  }

  depends_on = [module.config_and_routing]
}

resource "juju_integration" "certificates" {
  for_each   = { for app in local.certificates_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == var.certificates_integration.model_uuid ? var.certificates_integration.name : null
    endpoint  = each.value.model_uuid == var.certificates_integration.model_uuid ? var.certificates_integration.endpoint : null
    offer_url = each.value.model_uuid != var.certificates_integration.model_uuid ? var.certificates_integration.url : null
  }

  application {
    name     = local.certificates_requires[each.value.app_name].name
    endpoint = local.certificates_requires[each.value.app_name].endpoint
  }

  depends_on = [module.config_and_routing]
}

resource "juju_integration" "ldap" {
  for_each   = { for app in local.ldap_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == var.ldap_integration.model_uuid ? var.ldap_integration.name : null
    endpoint  = each.value.model_uuid == var.ldap_integration.model_uuid ? var.ldap_integration.endpoint : null
    offer_url = each.value.model_uuid != var.ldap_integration.model_uuid ? var.ldap_integration.url : null
  }

  application {
    name     = local.ldap_requires[each.value.app_name].name
    endpoint = local.ldap_requires[each.value.app_name].endpoint
  }

  depends_on = [module.config_and_routing]
}

resource "juju_integration" "ldap_certificate_transfer" {
  for_each   = { for app in local.ldap_certificate_transfer_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == var.ldap_certificate_transfer_integration.model_uuid ? var.ldap_certificate_transfer_integration.name : null
    endpoint  = each.value.model_uuid == var.ldap_certificate_transfer_integration.model_uuid ? var.ldap_certificate_transfer_integration.endpoint : null
    offer_url = each.value.model_uuid != var.ldap_certificate_transfer_integration.model_uuid ? var.ldap_certificate_transfer_integration.url : null
  }

  application {
    name     = local.ldap_certificate_transfer_requires[each.value.app_name].name
    endpoint = local.ldap_certificate_transfer_requires[each.value.app_name].endpoint
  }

  depends_on = [module.config_and_routing]
}
