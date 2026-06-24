## Requirements

| Name | Version |
|------|---------|
| Terraform | >= 1.6 |
| Juju provider | ~> 1.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| `juju_application.mongodb` | [Juju application](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `app_name` | Application name | `string` | `"mongodb"` | no |
| `base` | Charm base (old name: series) | `string` | `"ubuntu@24.04"` | no |
| `channel` | Charm channel | `string` | `"8/edge"` | no |
| `config` | Map of charm configuration options | `map(string)` | `{}` | no |
| `constraints`       | String listing constraints for this application | `string` | `"arch=amd64"` | no |
| `endpoint_bindings` | Map of endpoint bindings | `set(object)` | `[]` | no |
| `expose` | Expose the application for external access. | `list(object)` | `[]` | no |
| `machines` | List of machines for placement | `set(string)` | `[]` | no |
| `model_uuid` | Model UUID | `string` | n/a | yes |
| `revision` | Charm revision | `number` | `null` | no |
| `storage_directives` | Map of storage used by the application | `map(string)` | `{}` | no |
| `units` | Charm units | `number` | `3` | no |

## Outputs

| Name | Description |
|------|-------------|
| `application` | Object representing the deployed MongoDB application |
| `provides` | Map of all "provides" endpoints |
| `requires` | Map of all "requires" endpoints |
