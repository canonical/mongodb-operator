# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# Applications
#--------------------------------------------------------

variable "config_server" {
  description = "Config server app definition"
  type = object({
    app_name    = optional(string, "config-server")
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string, "8/stable")
    config      = optional(map(string), { "role" : "config-server" })
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
    machines           = optional(set(string), [])
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 3)
  })

  validation {
    condition     = var.config_server.config["role"] == "config-server"
    error_message = "Config option: 'role' must be set to 'config-server'."
  }

  validation {
    condition     = var.config_server.base == "ubuntu@24.04"
    error_message = "Config server base must be 'ubuntu@24.04'."
  }
}

variable "data_integrator" {
  description = "Configuration for the data-integrator"
  type = object({
    app_name    = optional(string, "data-integrator")
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string, "latest/edge")
    config      = optional(map(string), { "database-name" : "test", "extra-user-roles" : "admin" })
    constraints = optional(string, "arch=amd64")
    endpoint_bindings = optional(set(object({
      space    = string
      endpoint = optional(string)
    })), [])
    machines           = optional(set(string), [])
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 1)
  })

  validation {
    condition     = var.config_server.model_uuid == var.data_integrator.model_uuid
    error_message = "'mongos' and 'data_integrator' should have the same model_uuid."
  }

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

variable "mongos" {
  description = "Configuration for mongos"
  type = object({
    app_name = optional(string, "mongos")
    base     = optional(string, "ubuntu@24.04")
    channel  = optional(string, "8/stable")
    config   = optional(map(string), {})
    endpoint_bindings = optional(set(object({
      space    = string
      endpoint = optional(string)
    })), [])
    revision = optional(number, null)
  })
  default = {}

  validation {
    condition     = var.mongos.base == "ubuntu@24.04"
    error_message = "mongos base must be 'ubuntu@24.04'."
  }
}

variable "shards" {
  description = "Shard apps"
  type = list(object({
    app_name    = string
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string, "8/stable")
    config      = optional(map(string), { "role" : "shard" })
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
    machines           = optional(set(string), [])
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 3)
  }))
  default = []

  validation {
    condition     = alltrue([for shard in var.shards : (shard.config["role"] == "shard")])
    error_message = "Config option: 'role' must be set to 'shard' in all shard objects."
  }

  validation {
    condition     = alltrue([for shard in var.shards : shard.base == "ubuntu@24.04"])
    error_message = "All shard bases must be 'ubuntu@24.04'."
  }
}

variable "s3_integrator" {
  description = "Configuration for the S3 backup integrator"
  type = object({
    app_name = optional(string, "s3-integrator")
    base     = optional(string, "ubuntu@24.04")
    channel  = optional(string, "2/stable")
    config = optional(object({
      attributes                          = optional(string)
      bucket                              = optional(string)
      endpoint                            = optional(string)
      experimental-delete-older-than-days = optional(number)
      path                                = optional(string)
      region                              = optional(string)
      s3-api-version                      = optional(string)
      s3-uri-style                        = optional(string)
      storage-class                       = optional(string)
      tls-ca-chain                        = optional(string)
      credentials                         = optional(string)
    }), {})
    constraints = optional(string, "arch=amd64")
    model_uuid  = string
    revision    = optional(number, null)
    units       = optional(number, 1)
  })
  default = null

  validation {
    condition     = try(var.s3_integrator.units == 1, true)
    error_message = "Units count should be 1"
  }
}


#--------------------------------------------------------
# Integrations
#--------------------------------------------------------


variable "client_certificates_integration" {
  description = "Optional client TLS certificates integration target."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = (
      var.client_certificates_integration == null ? true : (
        var.client_certificates_integration.name != null && var.client_certificates_integration.name != "" &&
        var.client_certificates_integration.endpoint != null && var.client_certificates_integration.endpoint != "" &&
        var.client_certificates_integration.model_uuid != null && var.client_certificates_integration.model_uuid != ""
      )
    )
    error_message = "client_certificates_integration must include non-empty 'name', 'endpoint', and 'model_uuid' attributes."
  }
}

variable "cos_agent_integrations" {
  description = "Optional same-model COS agent integration targets keyed by config server or shard app name. Use one target per principal MongoDB application."
  type = map(object({
    name     = string
    endpoint = string
  }))
  default = {}

  validation {
    condition = alltrue([
      for app_name, integration in var.cos_agent_integrations :
      integration.name != "" && integration.endpoint != ""
    ])
    error_message = "cos_agent_integrations values must include non-empty 'name' and 'endpoint' attributes."
  }
}

variable "etcd_integration" {
  description = "Optional etcd integration target for MongoDB rolling operations."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = (
      var.etcd_integration == null ? true : (
        var.etcd_integration.name != null && var.etcd_integration.name != "" &&
        var.etcd_integration.endpoint != null && var.etcd_integration.endpoint != "" &&
        var.etcd_integration.model_uuid != null && var.etcd_integration.model_uuid != ""
      )
    )
    error_message = "etcd_integration must include non-empty 'name', 'endpoint', and 'model_uuid' attributes."
  }
}

variable "ldap_integration" {
  description = "Optional LDAP integration target. Must be configured together with ldap_certificate_transfer_integration."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = (
      var.ldap_integration == null ? true : (
        var.ldap_integration.name != null && var.ldap_integration.name != "" &&
        var.ldap_integration.endpoint != null && var.ldap_integration.endpoint != "" &&
        var.ldap_integration.model_uuid != null && var.ldap_integration.model_uuid != ""
      )
    )
    error_message = "ldap_integration must include non-empty 'name', 'endpoint', and 'model_uuid' attributes."
  }
}

variable "ldap_certificate_transfer_integration" {
  description = "Optional LDAP certificate transfer integration target. Must be configured together with ldap_integration."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = (
      var.ldap_certificate_transfer_integration == null ? true : (
        var.ldap_certificate_transfer_integration.name != null && var.ldap_certificate_transfer_integration.name != "" &&
        var.ldap_certificate_transfer_integration.endpoint != null && var.ldap_certificate_transfer_integration.endpoint != "" &&
        var.ldap_certificate_transfer_integration.model_uuid != null && var.ldap_certificate_transfer_integration.model_uuid != ""
      )
    )
    error_message = "ldap_certificate_transfer_integration must include non-empty 'name', 'endpoint', and 'model_uuid' attributes."
  }
}

variable "peer_certificates_integration" {
  description = "Optional peer TLS certificates integration target."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = (
      var.peer_certificates_integration == null ? true : (
        var.peer_certificates_integration.name != null && var.peer_certificates_integration.name != "" &&
        var.peer_certificates_integration.endpoint != null && var.peer_certificates_integration.endpoint != "" &&
        var.peer_certificates_integration.model_uuid != null && var.peer_certificates_integration.model_uuid != ""
      )
    )
    error_message = "peer_certificates_integration must include non-empty 'name', 'endpoint', and 'model_uuid' attributes."
  }
}

variable "vault_kv_integration" {
  description = "Optional Vault KV integration target for encryption at rest."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = (
      var.vault_kv_integration == null ? true : (
        var.vault_kv_integration.name != null && var.vault_kv_integration.name != "" &&
        var.vault_kv_integration.endpoint != null && var.vault_kv_integration.endpoint != "" &&
        var.vault_kv_integration.model_uuid != null && var.vault_kv_integration.model_uuid != ""
      )
    )
    error_message = "vault_kv_integration must include non-empty 'name', 'endpoint', and 'model_uuid' attributes."
  }
}


#--------------------------------------------------------
# Config
#--------------------------------------------------------

variable "s3_access_key" {
  description = "S3 access key."
  type        = string
  sensitive   = true
  default     = null
}

variable "s3_secret_key" {
  description = "S3 secret key."
  type        = string
  sensitive   = true
  default     = null
}

variable "logging_config" {
  description = "Logging configuration to be used"
  type        = string
  default     = "<root>=INFO"
}
