# Terraform module for gcs-integrator

This is a Terraform module facilitating the deployment of the GCS integrator charm with [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs).

## Requirements

| Name | Version |
|------|---------|
| `Terraform` | >= 1.6 |
| `Juju provider` | ~> 2.0  |

## Providers

| Name | Version |
| ---- | ------- |
| `juju` | ~> 2.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| `juju_application.gcs_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) |
| `juju_offer.gcs_credentials` | [Juju offer](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/offer) |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `app_name` | Name to give the deployed application. | `string` | `"gcs-integrator"` | no |
| `base` | The operating system on which to deploy. E.g. `ubuntu@24.04`. | `string` | `null` | no |
| `channel` | Channel of the charm. | `string` | `"1/stable"` | no |
| `config` | GCS integrator charm configuration options. | <pre>object({<br/>    bucket        = optional(string)<br/>    credentials   = optional(string)<br/>    path          = optional(string)<br/>    storage-class = optional(string)<br/>  })</pre> | `{}` | no |
| `constraints` | String listing constraints for this application. | `string` | `null` | no |
| `endpoint_bindings` | Set of endpoint bindings | <pre>set(object({<br/>    space    = string<br/>    endpoint = optional(string)<br/>  }))</pre> | `[]` | no |
| `machines` | List of machines for placement | `set(string)` | `[]` | no |
| `model_uuid` | Reference to an existing model uuid. | `string` | n/a | yes |
| `revision` | Revision number of the charm. | `number` | `null` | no |
| `storage_directives` | Map of storage directives (constraints) for the Juju application. | `map(string)` | `{}` | no |
| `units` | Unit count. | `number` | `1` | no |

### GCS config options

| Name | Description |
|------|-------------|
| `bucket` | Target GCS bucket for snapshots/backups. Must be 3-63 characters using lowercase letters, digits, and hyphens. |
| `credentials` | Juju Secret URI, such as `secret:xxxx`, containing a GCP service-account JSON key under `secret-key`. |
| `path` | Optional object prefix. Must be at most 1024 characters and must not contain NULL bytes. |
| `storage-class` | Optional GCS storage class. Must be one of `STANDARD`, `NEARLINE`, `COLDLINE`, or `ARCHIVE`. The charm default is `STANDARD`. |

## Outputs

| Name | Description |
|------|-------------|
| `application` | Object representing the deployed application. |
| `offers` | Map of all offers exposed by the single charm. |
| `provides` | Map of all "provides" endpoints. |
| `requires` | Map of all "requires" endpoints |
