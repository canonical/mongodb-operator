# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "config_server" {
  description = "Config server app definition"
  type = object({
    app_name    = string
    base        = optional(string, "ubuntu@22.04")
    channel     = optional(string, "6/stable")
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
    condition     = var.config_server.base == "ubuntu@22.04"
    error_message = "Config server base must be 'ubuntu@22.04'."
  }
}

variable "mongos" {
  description = "Configuration for mongos"
  type = object({
    app_name = optional(string, "mongos")
    base     = optional(string, "ubuntu@22.04")
    channel  = optional(string, "6/stable")
    config   = optional(map(string), {})
    endpoint_bindings = optional(set(object({
      space    = string
      endpoint = optional(string)
    })), [])
    revision = optional(number, null)
  })
  default = {}

  validation {
    condition     = var.mongos.base == "ubuntu@22.04"
    error_message = "mongos base must be 'ubuntu@22.04'."
  }
}
