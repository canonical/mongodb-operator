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
| `config_and_routing` | ../../components/sharded | n/a |
| `data_integrator` | ../../charms/data_integrator | n/a |
| `gcs_integrator` | ../../charms/gcs_integrator | n/a |
| `shards` | ../../charms/mongodb | n/a |

## Resources

| Name | Type | Description |
|------|------|-------------|
| `juju_application.s3_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | Optionally deploys the S3 integrator charm. Mutually exclusive with `module.gcs_integrator`. |
| `juju_integration.config_server_shards` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates shards to the config server, using a direct endpoint for same-model shards and an offer for cross-model shards. |
| `juju_integration.mongos_client` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates data-integrator to mongos in the config server model. |
| `juju_integration.s3_credentials` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates the config server to the optional S3 integrator. |
| `juju_integration.gcs_credentials` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates the config server to the optional GCS integrator. |
| `juju_integration.client_certificates` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB applications to an optional client TLS certificates target. |
| `juju_integration.cos_agent` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates configured MongoDB applications' `cos-agent` endpoints to same-model COS agents. |
| `juju_integration.etcd` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB applications to an optional etcd target. |
| `juju_integration.ldap` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates the config server and mongos to an optional LDAP target. |
| `juju_integration.ldap_certificate_transfer` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates the config server and mongos to an optional LDAP certificate transfer target. |
| `juju_integration.peer_certificates` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB applications to an optional peer TLS certificates target. |
| `juju_integration.vault_kv` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates MongoDB applications to an optional Vault KV target for encryption at rest. |
| `juju_offer.s3_credentials` | [Juju offer](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/offer) | Offers the S3 integrator credentials endpoint when S3 is cross-model. |
| `terraform_data.validate_backup_integrations` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures only one backup integrator is configured. |
| `terraform_data.validate_cos_agent_integrations` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures COS agent integration keys match MongoDB principal application names. |
| `terraform_data.validate_ldap_integrations` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures LDAP and LDAP certificate transfer are configured together. |
| `terraform_data.validate_cross_model_integration_urls` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures optional external integration targets provide an offer URL when cross-model relations are needed. |
| `terraform_data.deployed_at` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Stores the first deployment timestamp for product metadata. |



## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `config_server` | Config server app definition | <pre>object({<br/>    app_name    = optional(string, "config-server")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "8/stable")<br/>    config      = optional(map(string), { "role" : "config-server" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    expose = optional(list(object({<br/>      cidrs     = optional(string)<br/>      endpoints = optional(string)<br/>      spaces    = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 3)<br/>  })</pre> | n/a | yes |
| `data_integrator` | Configuration for the data-integrator | <pre>object({<br/>    app_name    = optional(string, "data-integrator")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "latest/edge")<br/>    config      = optional(map(string), { "database-name" : "test", "extra-user-roles" : "admin" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 1)<br/>  })</pre> | n/a | yes |
| `mongos` | Configuration for mongos | <pre>object({<br/>    app_name = optional(string, "mongos")<br/>    base     = optional(string, "ubuntu@24.04")<br/>    channel  = optional(string, "8/stable")<br/>    config   = optional(map(string), {})<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines = optional(set(string), null)<br/>    revision = optional(number, null)<br/>  })</pre> | n/a | yes |
| `shards` | Shard apps | <pre>list(object({<br/>    app_name    = string<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "8/stable")<br/>    config      = optional(map(string), { "role" : "shard" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    expose = optional(list(object({<br/>      cidrs     = optional(string)<br/>      endpoints = optional(string)<br/>      spaces    = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 3)<br/>  }))</pre> | `[]` | no |
| `s3_integrator` | Configuration for the S3 backup integrator | <pre>object({<br/>    app_name    = optional(string, "s3-integrator")<br/>    base        = optional(string, "ubuntu@22.04")<br/>    channel     = optional(string, "1/stable")<br/>    config      = map(string)<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 1)<br/>  })</pre> | `null` | no |
| `gcs_integrator` | Configuration for the GCS backup integrator | <pre>object({<br/>    app_name    = optional(string, "gcs-integrator")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "1/stable")<br/>    config      = map(string)<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 1)<br/>  })</pre> | `null` | no |
| `client_certificates_integration` | Optional client TLS certificates integration target. | <pre>object({<br/>    name       = optional(string, null)<br/>    endpoint   = optional(string, null)<br/>    model_uuid = optional(string, null)<br/>    url        = optional(string, null)<br/>  })</pre> | `null` | no |
| `cos_agent_integrations` | Optional same-model COS agent integration targets keyed by config server or shard app name. Use one target per principal MongoDB application. | <pre>map(object({<br/>    name     = string<br/>    endpoint = string<br/>  }))</pre> | `{}` | no |
| `etcd_integration` | Optional etcd integration target for MongoDB rolling operations. | <pre>object({<br/>    name       = optional(string, null)<br/>    endpoint   = optional(string, null)<br/>    model_uuid = optional(string, null)<br/>    url        = optional(string, null)<br/>  })</pre> | `null` | no |
| `ldap_integration` | Optional LDAP integration target. Must be configured together with ldap_certificate_transfer_integration. | <pre>object({<br/>    name       = optional(string, null)<br/>    endpoint   = optional(string, null)<br/>    model_uuid = optional(string, null)<br/>    url        = optional(string, null)<br/>  })</pre> | `null` | no |
| `ldap_certificate_transfer_integration` | Optional LDAP certificate transfer integration target. Must be configured together with ldap_integration. | <pre>object({<br/>    name       = optional(string, null)<br/>    endpoint   = optional(string, null)<br/>    model_uuid = optional(string, null)<br/>    url        = optional(string, null)<br/>  })</pre> | `null` | no |
| `logging_config` | Logging configuration to be used | `string` | `"<root>=INFO"` | no |
| `peer_certificates_integration` | Optional peer TLS certificates integration target. | <pre>object({<br/>    name       = optional(string, null)<br/>    endpoint   = optional(string, null)<br/>    model_uuid = optional(string, null)<br/>    url        = optional(string, null)<br/>  })</pre> | `null` | no |
| `vault_kv_integration` | Optional Vault KV integration target for encryption at rest. | <pre>object({<br/>    name       = optional(string, null)<br/>    endpoint   = optional(string, null)<br/>    model_uuid = optional(string, null)<br/>    url        = optional(string, null)<br/>  })</pre> | `null` | no |

Optional integration targets use this shape:

```hcl
{
  name       = string
  endpoint   = string
  model_uuid = string
  url        = optional(string)
}
```

When an optional integration is configured, `name`, `endpoint`, and `model_uuid` must be non-empty. If the target is cross-model from any MongoDB application that needs it, `url` must contain an offer URL created outside this module.

COS agent integrations are same-model and keyed by the config server or shard app name. Use one subordinate target per principal MongoDB application:

```hcl
cos_agent_integrations = {
  "config-server" = {
    name     = "opentelemetry-collector-config"
    endpoint = "cos-agent"
  }
  "shard-one" = {
    name     = "opentelemetry-collector-shard-one"
    endpoint = "cos-agent"
  }
  "shard-two" = {
    name     = "opentelemetry-collector-shard-two"
    endpoint = "cos-agent"
  }
}
```

## Outputs

| Name | Description |
|------|-------------|
| `components` | Deployed applications. Optional integrators return `null` when omitted. |
| `app_names` | Names of all deployed applications. Optional integrators return `null` when omitted. |
| `models` | Models and deployed components managed by this module, keyed by model UUID. |
| `metadata` | Metadata of the product deployment. |
| `provides` | Provided endpoint pointers from the sharded control plane and shards. |
| `requires` | Required endpoint pointers from the sharded control plane and shards. |
| `offers` | Cross-model offer endpoints created for product-owned applications, or `null` when not needed. |
