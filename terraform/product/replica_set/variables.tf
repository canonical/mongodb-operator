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
    channel     = optional(string, "8/stable")
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
  description = "Optional client TLS certificates integration target. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.client_certificates_integration == null || contains(["endpoint", "offer"], var.client_certificates_integration.kind)
    error_message = "client_certificates_integration.kind must be either \"endpoint\" or \"offer\"."
  }

  validation {
    condition = (
      var.client_certificates_integration == null ? true :
      var.client_certificates_integration.kind == "endpoint" ? (
        var.client_certificates_integration.name != null && var.client_certificates_integration.name != "" &&
        var.client_certificates_integration.endpoint != null && var.client_certificates_integration.endpoint != ""
      ) : true
    )
    error_message = "Both 'name' and 'endpoint' attributes must be provided for an in-model integration."
  }

  validation {
    condition = (
      var.client_certificates_integration == null ? true :
      var.client_certificates_integration.kind == "offer" ? (
        var.client_certificates_integration.url != null && var.client_certificates_integration.url != ""
      ) : true
    )
    error_message = "The 'url' attribute must be provided for a cross-model integration."
  }
}

variable "cos_agent_integration" {
  description = "Optional same-model COS agent integration target."
  type = object({
    name     = string
    endpoint = string
  })
  default = null
}

variable "etcd_integration" {
  description = "Optional etcd integration target for MongoDB rolling operations. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.etcd_integration == null || contains(["endpoint", "offer"], var.etcd_integration.kind)
    error_message = "etcd_integration.kind must be either \"endpoint\" or \"offer\"."
  }

  validation {
    condition = (
      var.etcd_integration == null ? true :
      var.etcd_integration.kind == "endpoint" ? (
        var.etcd_integration.name != null && var.etcd_integration.name != "" &&
        var.etcd_integration.endpoint != null && var.etcd_integration.endpoint != ""
      ) : true
    )
    error_message = "Both 'name' and 'endpoint' attributes must be provided for an in-model integration."
  }

  validation {
    condition = (
      var.etcd_integration == null ? true :
      var.etcd_integration.kind == "offer" ? (
        var.etcd_integration.url != null && var.etcd_integration.url != ""
      ) : true
    )
    error_message = "The 'url' attribute must be provided for a cross-model integration."
  }
}

variable "ldap_integration" {
  description = "Optional LDAP integration target. Must be configured together with ldap_certificate_transfer_integration. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.ldap_integration == null || contains(["endpoint", "offer"], var.ldap_integration.kind)
    error_message = "ldap_integration.kind must be either \"endpoint\" or \"offer\"."
  }

  validation {
    condition = (
      var.ldap_integration == null ? true :
      var.ldap_integration.kind == "endpoint" ? (
        var.ldap_integration.name != null && var.ldap_integration.name != "" &&
        var.ldap_integration.endpoint != null && var.ldap_integration.endpoint != ""
      ) : true
    )
    error_message = "Both 'name' and 'endpoint' attributes must be provided for an in-model integration."
  }

  validation {
    condition = (
      var.ldap_integration == null ? true :
      var.ldap_integration.kind == "offer" ? (
        var.ldap_integration.url != null && var.ldap_integration.url != ""
      ) : true
    )
    error_message = "The 'url' attribute must be provided for a cross-model integration."
  }
}

variable "ldap_certificate_transfer_integration" {
  description = "Optional LDAP certificate transfer integration target. Must be configured together with ldap_integration. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.ldap_certificate_transfer_integration == null || contains(["endpoint", "offer"], var.ldap_certificate_transfer_integration.kind)
    error_message = "ldap_certificate_transfer_integration.kind must be either \"endpoint\" or \"offer\"."
  }

  validation {
    condition = (
      var.ldap_certificate_transfer_integration == null ? true :
      var.ldap_certificate_transfer_integration.kind == "endpoint" ? (
        var.ldap_certificate_transfer_integration.name != null && var.ldap_certificate_transfer_integration.name != "" &&
        var.ldap_certificate_transfer_integration.endpoint != null && var.ldap_certificate_transfer_integration.endpoint != ""
      ) : true
    )
    error_message = "Both 'name' and 'endpoint' attributes must be provided for an in-model integration."
  }

  validation {
    condition = (
      var.ldap_certificate_transfer_integration == null ? true :
      var.ldap_certificate_transfer_integration.kind == "offer" ? (
        var.ldap_certificate_transfer_integration.url != null && var.ldap_certificate_transfer_integration.url != ""
      ) : true
    )
    error_message = "The 'url' attribute must be provided for a cross-model integration."
  }
}

variable "peer_certificates_integration" {
  description = "Optional peer TLS certificates integration target. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.peer_certificates_integration == null || contains(["endpoint", "offer"], var.peer_certificates_integration.kind)
    error_message = "peer_certificates_integration.kind must be either \"endpoint\" or \"offer\"."
  }

  validation {
    condition = (
      var.peer_certificates_integration == null ? true :
      var.peer_certificates_integration.kind == "endpoint" ? (
        var.peer_certificates_integration.name != null && var.peer_certificates_integration.name != "" &&
        var.peer_certificates_integration.endpoint != null && var.peer_certificates_integration.endpoint != ""
      ) : true
    )
    error_message = "Both 'name' and 'endpoint' attributes must be provided for an in-model integration."
  }

  validation {
    condition = (
      var.peer_certificates_integration == null ? true :
      var.peer_certificates_integration.kind == "offer" ? (
        var.peer_certificates_integration.url != null && var.peer_certificates_integration.url != ""
      ) : true
    )
    error_message = "The 'url' attribute must be provided for a cross-model integration."
  }
}

variable "vault_kv_integration" {
  description = "Optional Vault KV integration target for encryption at rest. Use kind = \"endpoint\" with name/endpoint for same-model integrations, or kind = \"offer\" with url for cross-model integrations."
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
  default = null

  validation {
    condition     = var.vault_kv_integration == null || contains(["endpoint", "offer"], var.vault_kv_integration.kind)
    error_message = "vault_kv_integration.kind must be either \"endpoint\" or \"offer\"."
  }

  validation {
    condition = (
      var.vault_kv_integration == null ? true :
      var.vault_kv_integration.kind == "endpoint" ? (
        var.vault_kv_integration.name != null && var.vault_kv_integration.name != "" &&
        var.vault_kv_integration.endpoint != null && var.vault_kv_integration.endpoint != ""
      ) : true
    )
    error_message = "Both 'name' and 'endpoint' attributes must be provided for an in-model integration."
  }

  validation {
    condition = (
      var.vault_kv_integration == null ? true :
      var.vault_kv_integration.kind == "offer" ? (
        var.vault_kv_integration.url != null && var.vault_kv_integration.url != ""
      ) : true
    )
    error_message = "The 'url' attribute must be provided for a cross-model integration."
  }
}

#--------------------------------------------------------
# Config
#--------------------------------------------------------

variable "s3_access_key" {
  description = "AWS S3 Access key."
  type        = string
  sensitive   = true
  default     = null
}

variable "s3_secret_key" {
  description = "AWS S3 Secret key."
  type        = string
  sensitive   = true
  default     = null
}

variable "logging_config" {
  description = "Logging configuration to be used"
  type        = string
  default     = "<root>=INFO"
}
