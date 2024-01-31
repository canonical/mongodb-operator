output "db_application_name" {
  description = "Name of the deployed application."
  value       = juju_application.mongodb-k8s.name
}