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
    channel     = optional(string, "8/edge")
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
    machines           = optional(set(string), null)
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 3)
  })

  validation {
    condition     = var.config_server.config["role"] == "config-server"
    error_message = "Config option: 'role' must be set to 'config-server'."
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
    machines           = optional(set(string), null)
    model_uuid         = string
    revision           = optional(number, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 1)
  })

  validation {
    condition     = var.mongos.model_uuid == var.data_integrator.model_uuid
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
    app_name   = optional(string, "mongos")
    base       = optional(string, "ubuntu@24.04")
    channel    = optional(string, "8/edge")
    config     = optional(map(string), {})
    model_uuid = string
    revision   = optional(number, null)
  })

  validation {
    condition     = var.mongos.model_uuid == var.config_server.model_uuid
    error_message = "'mongos' and 'config_server' should have the same model_uuid."
  }
}

variable "shards" {
  description = "Shard apps"
  type = list(object({
    app_name    = string
    base        = optional(string, "ubuntu@24.04")
    channel     = optional(string, "8/edge")
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
    machines           = optional(set(string), null)
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
  description = "Optional client TLS certificates integration target. Set name/endpoint/model_uuid for same-model integrations; set url for cross-model integrations."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = var.client_certificates_offer == null || (
      try(var.client_certificates_offer.url, null) != null
      || (
        try(var.client_certificates_offer.name, null) != null
        && try(var.client_certificates_offer.endpoint, null) != null
        && try(var.client_certificates_offer.model_uuid, null) != null
      )
    )
    error_message = "client_certificates_offer requires either url, or name, endpoint, and model_uuid."
  }

  validation {
    condition = var.client_certificates_offer == null || contains(
      [0, 3],
      length([
        for value in [
          try(var.client_certificates_offer.name, null),
          try(var.client_certificates_offer.endpoint, null),
          try(var.client_certificates_offer.model_uuid, null),
        ] : value if value != null
      ])
    )
    error_message = "client_certificates_offer name, endpoint, and model_uuid must be set together."
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
  description = "Optional etcd integration target for MongoDB rolling operations. Set name/endpoint/model_uuid for same-model integrations; set url for cross-model integrations."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = var.etcd_offer == null || (
      try(var.etcd_offer.url, null) != null
      || (
        try(var.etcd_offer.name, null) != null
        && try(var.etcd_offer.endpoint, null) != null
        && try(var.etcd_offer.model_uuid, null) != null
      )
    )
    error_message = "etcd_offer requires either url, or name, endpoint, and model_uuid."
  }

  validation {
    condition = var.etcd_offer == null || contains(
      [0, 3],
      length([
        for value in [
          try(var.etcd_offer.name, null),
          try(var.etcd_offer.endpoint, null),
          try(var.etcd_offer.model_uuid, null),
        ] : value if value != null
      ])
    )
    error_message = "etcd_offer name, endpoint, and model_uuid must be set together."
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
  description = "Optional peer TLS certificates integration target. Set name/endpoint/model_uuid for same-model integrations; set url for cross-model integrations."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = var.peer_certificates_offer == null || (
      try(var.peer_certificates_offer.url, null) != null
      || (
        try(var.peer_certificates_offer.name, null) != null
        && try(var.peer_certificates_offer.endpoint, null) != null
        && try(var.peer_certificates_offer.model_uuid, null) != null
      )
    )
    error_message = "peer_certificates_offer requires either url, or name, endpoint, and model_uuid."
  }

  validation {
    condition = var.peer_certificates_offer == null || contains(
      [0, 3],
      length([
        for value in [
          try(var.peer_certificates_offer.name, null),
          try(var.peer_certificates_offer.endpoint, null),
          try(var.peer_certificates_offer.model_uuid, null),
        ] : value if value != null
      ])
    )
    error_message = "peer_certificates_offer name, endpoint, and model_uuid must be set together."
  }
}

variable "vault_kv_offer" {
  description = "Optional Vault KV integration target for encryption at rest. Set name/endpoint/model_uuid for same-model integrations; set url for cross-model integrations."
  type = object({
    name       = optional(string, null)
    endpoint   = optional(string, null)
    model_uuid = optional(string, null)
    url        = optional(string, null)
  })
  default = null

  validation {
    condition = var.vault_kv_offer == null || (
      try(var.vault_kv_offer.url, null) != null
      || (
        try(var.vault_kv_offer.name, null) != null
        && try(var.vault_kv_offer.endpoint, null) != null
        && try(var.vault_kv_offer.model_uuid, null) != null
      )
    )
    error_message = "vault_kv_offer requires either url, or name, endpoint, and model_uuid."
  }

  validation {
    condition = var.vault_kv_offer == null || contains(
      [0, 3],
      length([
        for value in [
          try(var.vault_kv_offer.name, null),
          try(var.vault_kv_offer.endpoint, null),
          try(var.vault_kv_offer.model_uuid, null),
        ] : value if value != null
      ])
    )
    error_message = "vault_kv_offer name, endpoint, and model_uuid must be set together."
  }
}
