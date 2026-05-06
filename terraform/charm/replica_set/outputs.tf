# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_names" {
  description = "Names of of all deployed applications."
  value = {
    mongodb = juju_application.mongodb.name
  }
}


# Provided integration endpoints
output "provides" {
  description = "Map of all \"provides\" endpoints"
  value = {
    database      = "database"
    config_server = "config-server"
    cluster       = "cluster"
    cos_agent     = "cos-agent"
  }
}

# Required integration endpoints
output "requires" {
  description = "Map of all \"requires\" endpoints"
  value = {
    sharding                  = "sharding"
    peer_certificates         = "peer-certificates"
    client_certificates       = "client-certificates"
    s3_credentials            = "s3-credentials"
    ldap                      = "ldap"
    ldap_certificate_transfer = "ldap-certificate-transfer"
    etcd                      = "etcd"
  }
}
