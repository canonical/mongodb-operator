# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.mongodb-k8s.name
}

# Provided integration endpoints

output "database_endpoint" {
  description = "Name of the endpoint to provide the mongodb_client interface."
  value       = "database"
}

output "obsolete_endpoint" {
  description = "Name of the endpoint to provide the mongodb interface."
  value       = "obsolete"
}

output "cos_agent_endpoint" {
  description = "Name of the endpoint to provide the cos_agent interface."
  value       = "cos-agent"
}

output "config_server_endpoint" {
  description = "Name of the endpoint to provide the shards interface."
  value       = "config-server"
}

output "cluster_endpoint" {
  description = "Name of the endpoint to provide the config-server interface."
  value       = "cluster"
}

output "metrics_endpoint" {
  description = "Name of the endpoint to provide the prometheus_scrape interface."
  value       = "metrics-endpoint"
}

output "grafana_dashboard_endpoint" {
  description = "Name of the endpoint to provide the grafana_dashboard interface."
  value       = "grafana-dashboard"
}

# Required integration endpoints

output "certificates_endpoint" {
  description = "Name of the endpoint to provide the tls-certificates interface."
  value       = "certificates"
}

output "s3_credentials_endpoint" {
  description = "Name of the endpoint to provide the s3 interface."
  value       = "s3-credentials"
}

output "sharding_endpoint" {
  description = "Name of the endpoint to provide the shards interface."
  value       = "sharding"
}

output "logging_endpoint" {
  description = "Name of the endpoint to provide the loki_push_api relation interface."
  value       = "logging"
}