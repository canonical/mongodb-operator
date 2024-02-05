# MongoDB Operator Terraform module

This folder contains a base [Terraform][Terraform] module for the `mongodb-k8s` charm.

The module uses the [Terraform Juju provider][Terraform Juju provider] to model the charm deployment onto any Kubernetes environment managed by [Juju][Juju].

The base module is not intended to be deployed in separation (it is possible though), but should rather serve as a building block for higher level modules.

## Module structure

- **main.tf** - Defines the Juju application to be deployed.
- **variables.tf** - Allows customization of the deployment such as Juju model name, channel or application name and charm configuration.
- **output.tf** - Responsible for integrating the module with other Terraform modules, primarily by defining potential integration endpoints (charm integrations), but also by exposing the application name.
- **terraform.tf** - Defines the Terraform provider.

## Using mongodb-k8s base module in higher level modules

If you want to use `mongodb-operator` base module as part of your Terraform module, import it like shown below.

```text
module "mongodb-operator" {
  source = "git::https://github.com/canonical/mongodb-operator.git//terraform"
  
  model_name = "juju_model_name"
  
 (Customize configuration variables here if needed)

}
```

Create the integrations, for instance:

```text
resource "juju_integration" "amf-db" {
  model = var.model_name

  application {
    name     = module.amf.app_name
    endpoint = module.amf.database_endpoint
  }

  application {
    name     = module.mongodb.app_name
    endpoint = module.mongodb.database_endpoint
  }
}
```

Please check the available [integration pairs][integration pairs].

[Terraform]: https://www.terraform.io/
[Juju]: https://juju.is
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[integration pairs]: https://charmhub.io/mongodb-k8s/integrations?channel=6/edge
