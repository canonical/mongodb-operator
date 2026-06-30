# Terraform module for sharded components

This is a Terraform module facilitating the deployment of the sharded components with [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs). 


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

| Name | Source | Version |
|------|--------|---------|
| `config_server` | ../../charm/mongodb | n/a |
| `mongos` | git::https://github.com/canonical/mongos-operator//terraform?ref=rev586 | n/a |
| `shards` | ../../charm/mongodb | n/a |

## Resources

| Name | Type | Description |
|------|------|-------------|
| `juju_integration.config_server_shards` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates shards to the config server, using a direct endpoint for same-model shards and an offer for cross-model shards. |
| `juju_integration.config_server_mongos` | [Juju integration](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/integration) | Relates mongos to the config server. |
| `juju_offer.config_server_to_shard` | [Juju offer](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/offer) | Offers the config server endpoint for cross-model shard relations. |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `config_server` | Config server app definition | <pre>object({<br/>    app_name    = string<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "8/stable")<br/>    config      = optional(map(string), { "role" : "config-server" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    expose = optional(list(object({<br/>      cidrs     = optional(string)<br/>      endpoints = optional(string)<br/>      spaces    = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 3)<br/>  })</pre> | n/a | yes |
| `mongos` | Configuration for mongos | <pre>object({<br/>    app_name = optional(string, "mongos")<br/>    base     = optional(string, "ubuntu@24.04")<br/>    channel  = optional(string, "8/stable")<br/>    config   = optional(map(string), {})<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    machines = optional(set(string), null)<br/>    revision = optional(number, null)<br/>  })</pre> | n/a | yes |
| `shards` | Shard apps | <pre>list(object({<br/>    app_name    = string<br/>    base        = optional(string, "ubuntu@24.04")<br/>    channel     = optional(string, "8/stable")<br/>    config      = optional(map(string), { "role" : "shard" })<br/>    constraints = optional(string, "arch=amd64")<br/>    endpoint_bindings = optional(set(object({<br/>      space    = string<br/>      endpoint = optional(string)<br/>    })), [])<br/>    expose = optional(list(object({<br/>      cidrs     = optional(string)<br/>      endpoints = optional(string)<br/>      spaces    = optional(string)<br/>    })), [])<br/>    machines           = optional(set(string), null)<br/>    model_uuid         = string<br/>    revision           = optional(number, null)<br/>    storage_directives = optional(map(string), {})<br/>    units              = optional(number, 3)<br/>  }))</pre> | `[]` | no |

## Outputs

| Name | Description |
|------|-------------|
| `app_names` | Names of all deployed applications. |
| `components` | All deployed applications, including the config server, mongos, and shards. |
| `offers` | Map of offer endpoints. |
| `provides` | Map of all "provides" endpoints. |
| `requires` | Map of all "requires" endpoints. Includes config server, mongos, and per-shard endpoints. |
