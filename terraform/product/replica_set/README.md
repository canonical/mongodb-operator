## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.6 |
| Juju provider | ~> 1.0 |

## Module

| Name | Source | Version |
|------|--------|---------|
| mongodb | ../../charm/replica_set | n/a |

## Resources

| Name | Type | Description |
|------|------|-------------|
| `juju_application.data_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | Deploys the data-integrator charm. |
| `juju_application.s3_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | Optionally deploys the S3 integrator charm. Mutually exclusive with `juju_application.gcs_integrator`. |
| `juju_application.gcs_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | Optionally deploys the GCS integrator charm. Mutually exclusive with `juju_application.s3_integrator`. |
| `juju_integration.cos_agent` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB's `cos-agent` endpoint to a same-model COS agent. |
| `juju_integration.etcd` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional etcd target. |
| `juju_integration.client_certificates` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional client TLS certificates target. |
| `juju_integration.ldap` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional LDAP target. |
| `juju_integration.ldap_certificate_transfer` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional LDAP certificate transfer target. |
| `juju_integration.peer_certificates` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional peer TLS certificates target. |
| `juju_integration.vault_kv` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional Vault KV target for encryption at rest. |
| `juju_integration.mongodb_data` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates data-integrator to MongoDB, using an offer when cross-model. |
| `juju_integration.mongodb_s3` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to the optional S3 integrator. |
| `juju_integration.mongodb_gcs` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to the optional GCS integrator. |
| `juju_offer.mongodb_client` | [Juju offer](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/offer) | Offers MongoDB's `database` endpoint for cross-model data-integrator relations. |
| `juju_offer.s3_integrator` | [Juju offer](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/offer) | Offers the S3 integrator credentials endpoint when S3 is cross-model. |
| `juju_offer.gcs_integrator` | [Juju offer](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/offer) | Offers the GCS integrator credentials endpoint when GCS is cross-model. |
| `terraform_data.validate_backup_integrations` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures only one backup integrator is configured. |
| `terraform_data.validate_ldap_integrations` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures LDAP and LDAP certificate transfer are configured together. |



## Inputs

| Name | Description | Required |
|------|-------------|:--------:|
| `mongodb` | MongoDB application definition. | yes |
| `data_integrator` | data-integrator application definition. | yes |
| `s3_integrator` | Optional S3 backup integrator definition. Mutually exclusive with `gcs_integrator`. | no |
| `gcs_integrator` | Optional GCS backup integrator definition. Mutually exclusive with `s3_integrator`. | no |
| `cos_agent_offer` | Optional same-model COS agent endpoint target. | no |
| `etcd_offer` | Optional etcd integration target. | no |
| `client_certificates_offer` | Optional client TLS certificates integration target. | no |
| `ldap_offer` | Optional LDAP integration target. Must be set together with `ldap_certificate_transfer_offer`. | no |
| `ldap_certificate_transfer_offer` | Optional LDAP certificate transfer target. Must be set together with `ldap_offer`. | no |
| `peer_certificates_offer` | Optional peer TLS certificates integration target. | no |
| `vault_kv_offer` | Optional Vault KV integration target for encryption at rest. | no |

Offer-style integration targets use this shape:

```hcl
{
  kind     = "endpoint" # or "offer"
  name     = optional(string)
  endpoint = optional(string)
  url      = optional(string)
}
```

Use `kind = "endpoint"` with `name` and `endpoint` for same-model relations. Use `kind = "offer"` with `url` for cross-model relations.

## Outputs

| Name | Description |
|------|-------------|
| `components` | Names of deployed applications. Optional integrators return `null` when omitted. |
| `provides` | MongoDB provided endpoint pointers, including `mongodb_database` and `mongodb_cos_agent`. |
| `requires` | MongoDB required endpoint pointers, including S3 and GCS credentials endpoints. |
| `offers` | Cross-model offer URLs created by this module, or `null` when not needed. |
