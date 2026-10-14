## Requirements

| Name | Version |
|------|---------|
| `Terraform` | >= 1.11 |
| `Juju provider` | >= 2.2.1 |

## Providers

| Name | Version |
| ---- | ------- |
| `juju` | >= 2.2.1 |


## Module

| Name | Source | Version |
|------|--------|---------|
| `data_integrator` | git::https://github.com/canonical/data-integrator.git//terraform/charm/data_integrator | main |
| `gcs_integrator` | git::https://github.com/canonical/object-storage-integrator.git//gcs/terraform/charm/gcs_integrator | main |
| `mongodb` | ../../charms/mongodb | n/a |
| `s3_integrator` | git::https://github.com/canonical/object-storage-integrator.git//s3/terraform/charm/s3_integrator | main |

## Resources

| Name | Type | Description |
|------|------|-------------|
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
| `juju_secret.gcs_secret` | [Juju secret](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/secret) | Optionally stores the GCS service-account JSON key and passes its URI to the GCS integrator. |
| `juju_access_secret.gcs_secret_access` | [Juju secret access](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/access_secret) | Grants the optional GCS credentials secret to the GCS integrator application. |
| `juju_secret.tls_client_private_key` | [Juju secret](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/secret) | Optionally stores the client TLS private key and passes its URI to MongoDB. |
| `juju_access_secret.tls_client_private_key` | [Juju secret access](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/access_secret) | Grants MongoDB access to the optional client TLS private-key secret. |
| `juju_secret.tls_peer_private_key` | [Juju secret](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/secret) | Optionally stores the peer TLS private key and passes its URI to MongoDB. |
| `juju_access_secret.tls_peer_private_key` | [Juju secret access](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/access_secret) | Grants MongoDB access to the optional peer TLS private-key secret. |
| `terraform_data.validate_ldap_integrations` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures LDAP and LDAP certificate transfer are configured together. |
| `terraform_data.validate_encryption_at_rest` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Ensures Vault KV and the MongoDB encryption-at-rest config are configured together. |
| `terraform_data.deployed_at` | [Terraform data](https://developer.hashicorp.com/terraform/language/resources/terraform-data) | Stores the first deployment timestamp for product metadata. |



## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `mongodb` | MongoDB app definition | <pre>object({<br/>    app_name    = optional(string, "mongodb")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "8/stable")<br/>    config      = optional(map(string), { "role" : "replication" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    expose = optional(list(object({<br/>      cidrs     = optional(string)<br/>      endpoints = optional(string)<br/>      spaces    = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 3)<br/>  })</pre> | n/a | yes |
| `data_integrator` | Configuration for the data-integrator | <pre>object({<br/>    app_name    = optional(string, "data-integrator")<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "latest/stable")<br/>    config      = optional(map(string), { "database-name" : "test", "extra-user-roles" : "admin" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 1)<br/>  })</pre> | n/a | yes |
| `backups_integrator` | Optional configuration for the backup integrator, including the model in which it is deployed. `storage_type` selects either the S3 or GCS integrator. Cross-model relations use the integrator's Juju offer. When `channel` is omitted, S3 uses `2/stable` and GCS uses `1/stable`. | <pre>object({<br/>    storage_type = optional(string, "s3")<br/>    config       = map(string)<br/>    channel      = optional(string, null)<br/>    base         = optional(string, "ubuntu@24.04")<br/>    revision     = optional(number, null)<br/>    constraints  = optional(string, "arch=amd64")<br/>    machines     = optional(set(string), [])<br/>    model_uuid   = string<br/>  })</pre> | `null` | no |
| `client_certificates_integration` | Optional client TLS certificates integration target. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `cos_agent_integration` | Optional same-model COS agent endpoint target. | <pre>object({<br/>    name     = string<br/>    endpoint = string<br/>  })</pre> | `null` | no |
| `etcd_integration` | Optional etcd integration target for MongoDB rolling operations. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `ldap_integration` | Optional LDAP integration target. Must be configured together with ldap_certificate_transfer_integration. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `ldap_certificate_transfer_integration` | Optional LDAP certificate transfer integration target. Must be configured together with ldap_integration. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `gcs_secret_key` | Ephemeral credential; supply through `TF_VAR_gcs_secret_key` or `-var` at plan and apply. | `string` | `null` | no |
| `logging_config` | Logging configuration to be used | `string` | `"<root>=INFO"` | no |
| `peer_certificates_integration` | Optional peer TLS certificates integration target. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |
| `tls_client_private_key` | Ephemeral credential; supply through `TF_VAR_tls_client_private_key` or `-var` at plan and apply. | `string` | `null` | no |
| `tls_peer_private_key` | Ephemeral credential; supply through `TF_VAR_tls_peer_private_key` or `-var` at plan and apply. | `string` | `null` | no |
| `vault_kv_integration` | Optional Vault KV integration target for encryption at rest. Must be configured together with mongodb.config["enable-encryption-at-rest"]. Use kind = "endpoint" with name/endpoint for same-model integrations, or kind = "offer" with url for cross-model integrations. | <pre>object({<br/>    kind     = string<br/>    name     = optional(string, null)<br/>    endpoint = optional(string, null)<br/>    url      = optional(string, null)<br/>  })</pre> | `null` | no |

| `s3_access_key` | Ephemeral S3 credential; supply at plan and apply. | `string` | `null` | no |
| `s3_secret_key` | Ephemeral S3 credential; supply at plan and apply. | `string` | `null` | no |
| `tls_client_private_key_version` | 0 creates no secret; 1 creates it; increment to rotate. Ignored when `tls_client_private_key_secret_uri` is set. | `number` | `0` | no |
| `tls_client_private_key_secret_uri` | Existing Juju secret URI; takes priority over the credential and version. | `string` | `null` | no |
| `tls_peer_private_key_version` | 0 creates no secret; 1 creates it; increment to rotate. Ignored when `tls_peer_private_key_secret_uri` is set. | `number` | `0` | no |
| `tls_peer_private_key_secret_uri` | Existing Juju secret URI; takes priority over the credential and version. | `string` | `null` | no |
| `s3_secret_version` | 0 creates no secret; 1 creates it; increment to rotate. Ignored when `s3_secret_uri` is set. | `number` | `0` | no |
| `s3_secret_uri` | Existing Juju secret URI; takes priority over the credential and version. | `string` | `null` | no |
| `gcs_secret_version` | 0 creates no secret; 1 creates it; increment to rotate. Ignored when `gcs_secret_uri` is set. | `number` | `0` | no |
| `gcs_secret_uri` | Existing Juju secret URI; takes priority over the credential and version. | `string` | `null` | no |

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

## Configure secrets

Credentials are sensitive, ephemeral inputs. Secret resources use write-only values so Terraform omits credentials from state and saved plans. Supply credentials through `TF_VAR_<input>` or `-var` at both plan and apply; avoid credential `.tfvars` files.

| Credential inputs | Version input | Existing secret URI input | Required secret keys |
| --- | --- | --- | --- |
| `tls_client_private_key` | `tls_client_private_key_version` | `tls_client_private_key_secret_uri` | `private-key` (PEM) |
| `tls_peer_private_key` | `tls_peer_private_key_version` | `tls_peer_private_key_secret_uri` | `private-key` (PEM) |
| `s3_access_key`, `s3_secret_key` | `s3_secret_version` | `s3_secret_uri` | `access-key`, `secret-key` |
| `gcs_secret_key` | `gcs_secret_version` | `gcs_secret_uri` | `secret-key` (service-account JSON) |

Set a version to `1` to create a secret. Increment the version and supply the new credential together to rotate it. Both S3 keys share one version. With an unchanged version, credentials can be omitted for unrelated changes; changing a credential alone does not rotate it. Setting the version back to `0` removes the managed secret and grant. Backup secrets are used only when the matching integrator is enabled.

For example, with required application inputs already configured:

```bash
read -rs -p 'S3 access key: ' TF_VAR_s3_access_key; echo
read -rs -p 'S3 secret key: ' TF_VAR_s3_secret_key; echo
export TF_VAR_s3_access_key TF_VAR_s3_secret_key
terraform plan -var='s3_secret_version=1' -out=tfplan
terraform apply tfplan
unset TF_VAR_s3_access_key TF_VAR_s3_secret_key
```

Keep the version in your non-sensitive configuration for subsequent runs. Root modules forwarding credential inputs must also declare them `sensitive = true` and `ephemeral = true`.

An existing secret URI takes priority over the credential and version. The module creates no secret in this mode and grants the consuming application access to the supplied secret. It must be in the consuming application's model and contain the keys listed above. Both `secret:<id>` and `secret://<model-uuid>/<id>` are supported. MongoDB receives TLS URIs through its corresponding charm config options; backup integrators receive them through `credentials`.

### Migration

Previously, providing a credential enabled creation automatically. Set the corresponding version to `1` and supply the credential when migrating an existing managed secret. Existing resource addresses are preserved. Credentials previously written with `value` remain in historical state and saved plans; rotate them and handle retained copies accordingly. When switching to an existing secret URI, Terraform destroys the previously managed secret, so use a separate existing secret.
