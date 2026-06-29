# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "config_server" {
  description = "Config server app definition"
  type = object({
    app_name    = string
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
    machines           = optional(set(string), [])
    model_uuid         = string
    revision           = optional(string, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 3)
  })

  validation {
    condition     = var.config_server.config["role"] == "config-server"
    error_message = "Config option: 'role' must be set to 'config-server'."
  }
  # TODO: add validation mutual exclusion on machines / units?
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
    machines           = optional(set(string), [])
    model_uuid         = string
    revision           = optional(string, null)
    storage_directives = optional(map(string), {})
    units              = optional(number, 3)
  }))
  default = []

  validation {
    condition     = alltrue([for shard in var.shards : (shard.config["role"] == "shard")])
    error_message = "Config option: 'role' must be set to 'shard' in all shard objects."
  }
  # TODO: add validation mutual exclusion on machines / units?
}

variable "etcd_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}

# TODO: validate kind == offer or endpoint

variable "client_certificates_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}

variable "gcs_credentials_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}

variable "ldap_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}

variable "ldap_certificate_transfer_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}

variable "peer_certificates_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}


variable "s3_credentials_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}

variable "vault_kv_offer" {
  description = ""
  type = object({
    kind     = string
    name     = optional(string, null)
    endpoint = optional(string, null)
    url      = optional(string, null)
  })
}

# TODO validate only one backup integration
# TODO ldap, both integrations or nothing



variable "database_offer" {
  description = "URL to the database offer"
  type = string
}

variable "database_endpoint" {
  description = "Pointer to the database endpoint"
  type = object({
      name = optional(string, null)
      endpoint = optional(string, null)
  })
}

variable "cluster_offer" {
  description = "URL to the database offer"
  type = string
}

variable "cluster_endpoint" {
  description = "Pointer to the cluster endpoint"
  type = object({
      name = optional(string, null)
      endpoint = optional(string, null)
  })
}

variable "cos_agent_offer" {
  description = "URL to the database offer"
  type = string
}

variable "cos_agent_endpoint" {
  description = "Pointer to the COS agent endpoint"
  type = object({
      name = optional(string, null)
      endpoint = optional(string, null)
  })
}