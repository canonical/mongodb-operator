# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# 3. Integrations
#--------------------------------------------------------

# Integrators
resource "juju_integration" "gcs_credentials" {
  for_each   = var.gcs_integrator != null ? { "integrated" = var.gcs_integrator } : {}
  model_uuid = module.cluster.components["config_server"].model_uuid

  application {
    name     = module.cluster.requires["config_server_gcs_credentials"].name
    endpoint = module.cluster.requires["config_server_gcs_credentials"].endpoint
  }

  application {
    name      = each.value.model_uuid == module.cluster.components["config_server"].model_uuid ? each.value.app_name : null
    endpoint  = each.value.model_uuid == module.cluster.components["config_server"].model_uuid ? "gcs-credentials" : null
    offer_url = try(juju_offer.gcs_credentials["offered"].url, null)
  }

  depends_on = [
    module.cluster,
    juju_application.gcs_integrator["deployed"],
  ]
}

resource "juju_integration" "mongos_client" {
  model_uuid = module.cluster.components["mongos"].model_uuid

  application {
    name     = module.cluster.requires["mongos_proxy"].name
    endpoint = module.cluster.requires["mongos_proxy"].endpoint
  }

  application {
    name      = juju_application.data_integrator.model_uuid == module.cluster.components["mongos"].model_uuid ? juju_application.data_integrator.name : null
    endpoint  = juju_application.data_integrator.model_uuid == module.cluster.components["mongos"].model_uuid ? "mongos" : null
    offer_url = try(juju_offer.mongos_client["offered"].url, null)
  }

  depends_on = [
    module.cluster,
    juju_application.data_integrator,
  ]
}

resource "juju_integration" "s3_credentials" {
  for_each   = var.s3_integrator != null ? { "integrated" = true } : {}
  model_uuid = module.cluster.components["config_server"].model_uuid

  application {
    name     = module.cluster.requires["config_server_s3_credentials"].name
    endpoint = module.cluster.requires["config_server_s3_credentials"].endpoint
  }

  application {
    name      = var.s3_integrator.model_uuid == module.cluster.components["config_server"].model_uuid ? module.s3_integrator[0].provides.s3_credentials.name : null
    endpoint  = var.s3_integrator.model_uuid == module.cluster.components["config_server"].model_uuid ? module.s3_integrator[0].provides.s3_credentials.endpoint : null
    offer_url = var.s3_integrator.model_uuid != module.cluster.components["config_server"].model_uuid ? module.s3_integrator[0].offers.s3_credentials.url : null
  }

  depends_on = [
    module.cluster,
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

  depends_on = [module.cluster]
}

resource "juju_integration" "client_certificates" {
  for_each   = { for app in local.client_certificates_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == var.client_certificates_integration.model_uuid ? var.client_certificates_integration.name : null
    endpoint  = each.value.model_uuid == var.client_certificates_integration.model_uuid ? var.client_certificates_integration.endpoint : null
    offer_url = each.value.model_uuid != var.client_certificates_integration.model_uuid ? var.client_certificates_integration.url : null
  }

  application {
    name     = local.client_certificates_requires[each.value.app_name].name
    endpoint = local.client_certificates_requires[each.value.app_name].endpoint
  }

  depends_on = [module.cluster]
}

resource "juju_integration" "etcd" {
  for_each   = { for app in local.etcd_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == var.etcd_integration.model_uuid ? var.etcd_integration.name : null
    endpoint  = each.value.model_uuid == var.etcd_integration.model_uuid ? var.etcd_integration.endpoint : null
    offer_url = each.value.model_uuid != var.etcd_integration.model_uuid ? var.etcd_integration.url : null
  }

  application {
    name     = local.etcd_requires[each.value.app_name].name
    endpoint = local.etcd_requires[each.value.app_name].endpoint
  }

  depends_on = [module.cluster]
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

  depends_on = [module.cluster]
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

  depends_on = [module.cluster]
}

resource "juju_integration" "peer_certificates" {
  for_each   = { for app in local.peer_certificates_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == var.peer_certificates_integration.model_uuid ? var.peer_certificates_integration.name : null
    endpoint  = each.value.model_uuid == var.peer_certificates_integration.model_uuid ? var.peer_certificates_integration.endpoint : null
    offer_url = each.value.model_uuid != var.peer_certificates_integration.model_uuid ? var.peer_certificates_integration.url : null
  }

  application {
    name     = local.peer_certificates_requires[each.value.app_name].name
    endpoint = local.peer_certificates_requires[each.value.app_name].endpoint
  }

  depends_on = [module.cluster]
}

resource "juju_integration" "vault_kv" {
  for_each   = { for app in local.vault_kv_apps : app.app_name => app }
  model_uuid = each.value.model_uuid

  application {
    name      = each.value.model_uuid == var.vault_kv_integration.model_uuid ? var.vault_kv_integration.name : null
    endpoint  = each.value.model_uuid == var.vault_kv_integration.model_uuid ? var.vault_kv_integration.endpoint : null
    offer_url = each.value.model_uuid != var.vault_kv_integration.model_uuid ? var.vault_kv_integration.url : null
  }

  application {
    name     = local.vault_kv_requires[each.value.app_name].name
    endpoint = local.vault_kv_requires[each.value.app_name].endpoint
  }

  depends_on = [module.cluster]
}
