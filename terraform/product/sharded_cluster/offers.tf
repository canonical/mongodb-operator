# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# 2. Offers
#--------------------------------------------------------

# Integrators
resource "juju_offer" "gcs_credentials" {
  for_each = try(var.gcs_integrator.model_uuid != module.cluster.components["config_server"].model_uuid, false) ? { "offered" = var.gcs_integrator } : {}

  application_name = each.value.app_name
  endpoints        = ["gcs-credentials"]
  depends_on       = [juju_application.gcs_integrator["deployed"]]
  model_uuid       = each.value.model_uuid
}

resource "juju_offer" "mongos_client" {
  for_each = juju_application.data_integrator.model_uuid != module.cluster.components["mongos"].model_uuid ? { "offered" = true } : {}

  application_name = juju_application.data_integrator.name
  endpoints        = ["mongos"]
  depends_on       = [module.cluster, juju_application.data_integrator]
  model_uuid       = juju_application.data_integrator.model_uuid
}
