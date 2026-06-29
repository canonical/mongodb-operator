# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# Applications
#--------------------------------------------------------

variable "data_integrator" {
  description = "Configuration for the data-integrator"
  type = object({
    app_name    = optional(string, "data-integrator")
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string, "latest/stable")
    config      = optional(map(string), { "database-name" : "test", "extra-user-roles" : "admin" })
    constraints = optional(string, "arch=amd64")
    endpoint_bindings = optional(set(object({
      space    = string
      endpoint = optional(string)
    })), [])
    machines           = optional(set(string), null)
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 1)
  })

  validation {
    condition     = var.data_integrator.machines == null || length(var.data_integrator.machines) <= 1
    error_message = "Machine count should be at most 1"
  }
  validation {
    condition     = var.data_integrator.units == 1
    error_message = "Units count should be 1"
  }
  validation {
    condition = (
      lookup(var.data_integrator.config, "database-name", "") != ""
      && contains(["default", "admin"], lookup(var.data_integrator.config, "extra-user-roles", "admin"))
    )
    error_message = "data-integrator config must contain a non-empty 'database-name' and 'extra-user-roles' must be either 'default' or 'admin'."
  }
}

variable "gcs_integrator" {
  description = "Configuration for the GCS backup integrator"
  type = object({
    app_name    = optional(string, "gcs-integrator")
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string, "1/stable")
    config      = map(string)
    constraints = optional(string, "arch=amd64")
    endpoint_bindings = optional(set(object({
      space    = string
      endpoint = optional(string)
    })), [])
    machines           = optional(set(string), null)
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 1)
  })
  default = null

  validation {
    condition     = try(var.gcs_integrator.machines == null || length(var.gcs_integrator.machines) <= 1, true)
    error_message = "Machines count should be at most 1"
  }
  validation {
    condition     = try(var.gcs_integrator.units == 1, true)
    error_message = "Units count should be 1"
  }
}

variable "mongodb" {
  description = "MongoDB app definition"
  type = object({
    app_name    = optional(string, "mongodb")
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string, "8/edge")
    config      = optional(map(string), { "role" : "replication" })
    constraints = optional(string, "arch=amd64")
    endpoint_bindings = optional(set(object({
      space    = string
      endpoint = optional(string)
    })), [])
    expose = optional(list(object({
      cidrs     = optional(string)
      endpoints = optional(string)
      spaces    = optional(string)
    })), [])
    machines           = optional(set(string), null)
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 3)
  })
}


variable "s3_integrator" {
  description = "Configuration for the S3 backup integrator"
  type = object({
    app_name    = optional(string, "s3-integrator")
    base        = optional(string, "ubuntu@22.04")
    channel     = optional(string, "1/stable")
    config      = map(string)
    constraints = optional(string, "arch=amd64")
    endpoint_bindings = optional(set(object({
      space    = string
      endpoint = optional(string)
    })), [])
    machines           = optional(set(string), null)
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 1)
  })
  default = null

  validation {
    condition     = try(var.s3_integrator.machines == null || length(var.s3_integrator.machines) <= 1, true)
    error_message = "Machines count should be at most 1"
  }
  validation {
    condition     = try(var.s3_integrator.units == 1, true)
    error_message = "Units count should be 1"
  }
}


#--------------------------------------------------------
# Integrations
#--------------------------------------------------------

variable "client_certificates_offer" {
  description = "Optional client TLS certificates integration target. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.client_certificates_offer == null || contains(["endpoint", "offer"], var.client_certificates_offer.kind)
    error_message = "client_certificates_offer.kind must be either \"endpoint\" or \"offer\"."
  }
}

variable "cos_agent_offer" {
  description = "Optional same-model COS agent integration target."
  type = object({
    name     = string
    endpoint = string
  })
  default = null
}

variable "etcd_offer" {
  description = "Optional etcd integration target for MongoDB rolling operations. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.etcd_offer == null || contains(["endpoint", "offer"], var.etcd_offer.kind)
    error_message = "etcd_offer.kind must be either \"endpoint\" or \"offer\"."
  }
}

variable "ldap_offer" {
  description = "Optional LDAP integration target. Must be configured together with ldap_certificate_transfer_offer. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.ldap_offer == null || contains(["endpoint", "offer"], var.ldap_offer.kind)
    error_message = "ldap_offer.kind must be either \"endpoint\" or \"offer\"."
  }
}

variable "ldap_certificate_transfer_offer" {
  description = "Optional LDAP certificate transfer integration target. Must be configured together with ldap_offer. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.ldap_certificate_transfer_offer == null || contains(["endpoint", "offer"], var.ldap_certificate_transfer_offer.kind)
    error_message = "ldap_certificate_transfer_offer.kind must be either \"endpoint\" or \"offer\"."
  }
}

variable "peer_certificates_offer" {
  description = "Optional peer TLS certificates integration target. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.peer_certificates_offer == null || contains(["endpoint", "offer"], var.peer_certificates_offer.kind)
    error_message = "peer_certificates_offer.kind must be either \"endpoint\" or \"offer\"."
  }
}

variable "vault_kv_offer" {
  description = "Optional Vault KV integration target for encryption at rest. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.vault_kv_offer == null || contains(["endpoint", "offer"], var.vault_kv_offer.kind)
    error_message = "vault_kv_offer.kind must be either \"endpoint\" or \"offer\"."
  }
}

#--------------------------------------------------------
# Config
#--------------------------------------------------------

variable "logging_config" {
  description = "Logging configuration to be used"
  type        = string
  default     = "<root>=INFO"
}