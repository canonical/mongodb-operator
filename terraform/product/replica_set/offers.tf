# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

#--------------------------------------------------------
# 2. Offers
#--------------------------------------------------------

resource "juju_offer" "mongodb_client" {
  for_each = var.data_integrator.model_uuid != module.mongodb.application.model_uuid ? { "offered" = true } : {}

  application_name = module.mongodb.application.name
  endpoints        = [module.mongodb.provides["database"]]
  depends_on       = [module.mongodb]
  model_uuid       = module.mongodb.application.model_uuid
}

resource "juju_offer" "s3_integrator" {
  for_each = try(var.s3_integrator.model_uuid != module.mongodb.application.model_uuid, false) ? { "offered" = var.s3_integrator } : {}

  application_name = each.value.app_name
  endpoints        = ["s3-credentials"]
  depends_on       = [juju_application.s3_integrator["deployed"]]
  model_uuid       = each.value.model_uuid
}

resource "juju_offer" "gcs_integrator" {
  for_each = try(var.gcs_integrator.model_uuid != module.mongodb.application.model_uuid, false) ? { "offered" = var.gcs_integrator } : {}

  application_name = each.value.app_name
  endpoints        = ["gcs-credentials"]
  depends_on       = [juju_application.gcs_integrator["deployed"]]
  model_uuid       = each.value.model_uuid
}
