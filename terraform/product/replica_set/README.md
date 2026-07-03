## Requirements

| Name | Version |
|------|---------|
| `Terraform` | >= 1.6 |
| `Juju provider` | ~> 2.0 |

## Providers

| Name | Version |
| ---- | ------- |
| `juju` | ~> 2.0 |


## Module

| Name | Source | Version |
|------|--------|---------|
| mongodb | ../../charm/mongodb | n/a |

## Resources

| Name | Type | Description |
|------|------|-------------|
| `juju_application.data_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | Deploys the data-integrator charm. |
| `juju_application.s3_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | Optionally deploys the S3 integrator charm. Mutually exclusive with `juju_application.gcs_integrator`. |
| `juju_application.gcs_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | Optionally deploys the GCS integrator charm. Mutually exclusive with `juju_application.s3_integrator`. |
| `juju_integration.client_certificates` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional client TLS certificates target. |
| `juju_integration.cos_agent` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB's `cos-agent` endpoint to a same-model COS agent. |
| `juju_integration.etcd` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB to an optional etcd target. |
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
| `terraform_data.deployed_at` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Stores the first deployment timestamp for product metadata. |



## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `mongodb` | MongoDB app definition | <pre>object({<br/>    app_name    = optional(string, "mongodb")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "8/stable")<br/>    config      = optional(map(string), { "role" : "replication" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    expose = optional(list(object({<br/>      cidrs     = optional(string)<br/>      endpoints = optional(string)<br/>      spaces    = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 3)<br/>  })</pre> | n/a | yes |
| `data_integrator` | Configuration for the data-integrator | <pre>object({<br/>    app_name    = optional(string, "data-integrator")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "latest/stable")<br/>    config      = optional(map(string), { "database-name" : "test", "extra-user-roles" : "admin" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 1)<br/>  })</pre> | n/a | yes |
| `s3_integrator` | Configuration for the S3 backup integrator | <pre>object({<br/>    app_name    = optional(string, "s3-integrator")<br/>    base        = optional(string, "ubuntu@22.04")<br/>    channel     = optional(string, "1/stable")<br/>    config      = map(string)<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 1)<br/>  })</pre> | `null` | no |
| `gcs_integrator` | Configuration for the GCS backup integrator | <pre>object({<br/>    app_name    = optional(string, "gcs-integrator")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "1/stable")<br/>    config      = map(string)<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 1)<br/>  })</pre> | `null` | no |
| `client_certificates_integration` | Optional client TLS certificates integration target. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `cos_agent_integration` | Optional same-model COS agent endpoint target. | <pre>object({<br/>    name     = string<br/>    endpoint = string<br/>  })</pre> | `null` | no |
| `etcd_integration` | Optional etcd integration target for MongoDB rolling operations. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `ldap_integration` | Optional LDAP integration target. Must be configured together with ldap_certificate_transfer_integration. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `ldap_certificate_transfer_integration` | Optional LDAP certificate transfer integration target. Must be configured together with ldap_integration. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `logging_config` | Logging configuration to be used | `string` | `"<root>=INFO"` | no |
| `peer_certificates_integration` | Optional peer TLS certificates integration target. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `vault_kv_integration` | Optional Vault KV integration target for encryption at rest. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |

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
| `components` | Deployed applications. Optional integrators return `null` when omitted. |
| `metadata` | Metadata of the product deployment. |
| `models` | Models and deployed components managed by this module, keyed by model UUID. |
| `provides` | MongoDB provided endpoint pointers, including `mongodb_database` and `mongodb_cos_agent`. |
| requires | MongoDB required endpoint pointers, including S3 and GCS credentials endpoints. |
| `offers` | Cross-model offer URLs created by this module, or `null` when not needed. |
