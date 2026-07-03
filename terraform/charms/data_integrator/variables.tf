# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

variable "app_name" {
  description = "Name to give the deployed application."
  type        = string
  default     = "data-integrator"
  nullable    = false
}

variable "base" {
  description = "The operating system on which to deploy. E.g. ubuntu@24.04."
  type        = string
  default     = null
}

variable "channel" {
  description = "Channel of the charm."
  type        = string
  default     = "latest/edge"
  nullable    = false
}

variable "config" {
  description = "Map for configuration options."
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "String listing constraints for this application."
  type        = string
  default     = null
}

variable "endpoint_bindings" {
  description = "Map of endpoint bindings"
  type = set(object({
    space    = string
    endpoint = optional(string)
  }))
  default = []
}

variable "machines" {
  description = "List of machines for placement"
  type        = set(string)
  default     = []
}

variable "model_uuid" {
  description = "Reference to an existing model uuid."
  type        = string
  nullable    = false
}

variable "storage_directives" {
  description = "Map of storage directives (constraints) for the juju application"
  type        = map(string)
  default     = {}
}

variable "revision" {
  description = "Revision number of the charm."
  type        = number
  default     = null
}

variable "units" {
  description = "Unit count."
  type        = number
  default     = 1
}
