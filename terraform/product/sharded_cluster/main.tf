# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


#--------------------------------------------------------
# 1. DEPLOYMENTS
#--------------------------------------------------------

module "cluster" {
  source = "../../components/sharded"

  config_server = var.config_server
  mongos        = var.mongos
  shards        = var.shards
}

resource "terraform_data" "validate_backup_integrations" {
  input = local.backup_integrations

  lifecycle {
    precondition {
      condition     = length(local.backup_integrations) <= 1
      error_message = "Only one backup integrator can be configured: set either s3_integrator or gcs_integrator, not both."
    }
  }
}

resource "terraform_data" "validate_ldap_integrations" {
  input = local.ldap_integrations

  lifecycle {
    precondition {
      condition     = length(local.ldap_integrations) == 0 || length(local.ldap_integrations) == 2
      error_message = "LDAP integrations must be configured together: set both ldap_integration and ldap_certificate_transfer_integration, or neither."
    }
  }
}

resource "terraform_data" "validate_cross_model_integration_urls" {
  input = {
    client_certificates_cross_model_apps       = local.client_certificates_cross_model_apps
    etcd_cross_model_apps                      = local.etcd_cross_model_apps
    ldap_cross_model_apps                      = local.ldap_cross_model_apps
    ldap_certificate_transfer_cross_model_apps = local.ldap_certificate_transfer_cross_model_apps
    peer_certificates_cross_model_apps         = local.peer_certificates_cross_model_apps
    vault_kv_cross_model_apps                  = local.vault_kv_cross_model_apps
  }

  lifecycle {
    precondition {
      condition     = length(local.client_certificates_cross_model_apps) == 0 || try(var.client_certificates_integration.url != null && var.client_certificates_integration.url != "", false)
      error_message = "client_certificates_integration.url must be provided when client certificates is cross-model from any MongoDB application."
    }
    precondition {
      condition     = length(local.etcd_cross_model_apps) == 0 || try(var.etcd_integration.url != null && var.etcd_integration.url != "", false)
      error_message = "etcd_integration.url must be provided when etcd is cross-model from any MongoDB application."
    }
    precondition {
      condition     = length(local.ldap_cross_model_apps) == 0 || try(var.ldap_integration.url != null && var.ldap_integration.url != "", false)
      error_message = "ldap_integration.url must be provided when LDAP is cross-model from the config server or mongos."
    }
    precondition {
      condition     = length(local.ldap_certificate_transfer_cross_model_apps) == 0 || try(var.ldap_certificate_transfer_integration.url != null && var.ldap_certificate_transfer_integration.url != "", false)
      error_message = "ldap_certificate_transfer_integration.url must be provided when LDAP certificate transfer is cross-model from the config server or mongos."
    }
    precondition {
      condition     = length(local.peer_certificates_cross_model_apps) == 0 || try(var.peer_certificates_integration.url != null && var.peer_certificates_integration.url != "", false)
      error_message = "peer_certificates_integration.url must be provided when peer certificates is cross-model from any MongoDB application."
    }
    precondition {
      condition     = length(local.vault_kv_cross_model_apps) == 0 || try(var.vault_kv_integration.url != null && var.vault_kv_integration.url != "", false)
      error_message = "vault_kv_integration.url must be provided when Vault KV is cross-model from any MongoDB application."
    }
  }
}

# Integrator apps
resource "juju_application" "data_integrator" {
  charm {
    name     = "data-integrator"
    channel  = var.data_integrator.channel
    revision = var.data_integrator.revision
    base     = var.data_integrator.base
  }

  name               = var.data_integrator.app_name
  config             = var.data_integrator.config
  constraints        = var.data_integrator.constraints
  endpoint_bindings  = var.data_integrator.endpoint_bindings
  machines           = (var.data_integrator.machines == null || length(var.data_integrator.machines) == 0) ? null : var.data_integrator.machines
  model_uuid         = var.data_integrator.model_uuid
  storage_directives = var.data_integrator.storage_directives
  units              = (var.data_integrator.machines == null || length(var.data_integrator.machines) == 0) ? var.data_integrator.units : null
}

resource "juju_application" "gcs_integrator" {
  for_each = var.gcs_integrator != null ? { "deployed" = var.gcs_integrator } : {}

  charm {
    name     = "gcs-integrator"
    channel  = each.value.channel
    revision = each.value.revision
    base     = each.value.base
  }

  name               = each.value.app_name
  config             = each.value.config
  constraints        = each.value.constraints
  endpoint_bindings  = each.value.endpoint_bindings
  machines           = (each.value.machines == null || length(each.value.machines) == 0) ? null : each.value.machines
  model_uuid         = each.value.model_uuid
  storage_directives = each.value.storage_directives
  units              = (each.value.machines == null || length(each.value.machines) == 0) ? each.value.units : null
}

resource "juju_application" "s3_integrator" {
  for_each = var.s3_integrator != null ? { "deployed" = var.s3_integrator } : {}

  charm {
    name     = "s3-integrator"
    channel  = each.value.channel
    revision = each.value.revision
    base     = each.value.base
  }

  name               = each.value.app_name
  config             = each.value.config
  constraints        = each.value.constraints
  endpoint_bindings  = each.value.endpoint_bindings
  machines           = (each.value.machines == null || length(each.value.machines) == 0) ? null : each.value.machines
  model_uuid         = each.value.model_uuid
  storage_directives = each.value.storage_directives
  units              = (each.value.machines == null || length(each.value.machines) == 0) ? each.value.units : null
}
