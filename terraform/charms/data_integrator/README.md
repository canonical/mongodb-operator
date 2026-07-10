# Terraform module for mongodb-operator

This is a Terraform module facilitating the deployment of the MongoDB charm with [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs). 

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
| `juju_application.data_integrator` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `app_name` | Application name | `string` | `"data_integrator"` | no |
| `base` | Charm base (old name: series) | `string` | `"ubuntu@24.04"` | no |
| `channel` | Charm channel | `string` | `"lates/stable"` | no |
| `config` | Map of charm configuration options | `map(string)` | `{}` | no |
| `constraints`       | String listing constraints for this application | `string` | `"arch=amd64"` | no |
| `endpoint_bindings` | Set of endpoint bindings | <pre>set(object({<br/>    space    = string<br/>    endpoint = optional(string)<br/>  }))</pre> | `[]` | no |
| `machines` | List of machines for placement | `set(string)` | `[]` | no |
| `model_uuid` | Model UUID | `string` | n/a | yes |
| `revision` | Charm revision | `number` | `null` | no |
| `storage_directives` | Map of storage used by the application | `map(string)` | `{}` | no |
| `units` | Charm units | `number` | `1` | no |

## Outputs

| Name | Description |
|------|-------------|
| `application` | Object representing the deployed MongoDB application |
| `offers` | Map of all offers exposed by the single charm. |
| `provides` | Map of all "provides" endpoints |
| `requires` | Map of all "requires" endpoints |
