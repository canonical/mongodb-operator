# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

variable "model_name" {
  description = "Name of Juju model to deploy application to"
  type        = string
  default     = ""
}

variable "app_name" {
  description = "Name of the application in the Juju model"
  type        = string
  default     = "mongodb"
}

variable "channel" {
  description = "The channel to use when deploying a charm"
  type        = string
  default     = "6/beta"
}

variable "mongo-config" {
  description = "Additional configuration for the MongoDB"
  default     = {}
}