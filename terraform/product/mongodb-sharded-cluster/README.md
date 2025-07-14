# MongoDB Sharded Deployment with Observability and Integrations

This Terraform module deploys a sharded MongoDB setup using Juju and includes related observability and integration components. The configuration supports:

- MongoDB config server and shards
- Mongos routers
- Observability with Grafana Agent
- Integrations with data and backup solutions
- Optional support for self-signed certificates

## Structure

This project uses Juju charms to deploy and relate a full MongoDB sharded stack with observability and integrations. It supports deploying across one or more Juju models.

### Components

- **Config Server** (`config-server`): Central metadata storage for MongoDB sharding.
- **Shards** (`sharded`, `apps`): Actual data storage shards, including additional shard applications.
- **Mongos Router** (`mongos`): MongoDB router that connects applications to shards.
- **Grafana Agent** (`grafana-agent`): Observability agent deployed to each model.
- **Data Integrator** (`data-integrator`): Manages data indexing and user roles.
- **Backups Integrator** (`backups-integrator`): Integrates MongoDB with backup storage.
- **Self-signed Certificates** (`self-signed-certificates`): Optional TLS for secure communications.

## Prerequisites

- [Terraform](https://www.terraform.io/) >= 1.3
- [Juju](https://juju.is/) with access to a controller and models
- Access to MongoDB and integrator charms

## Usage

Clone this repository and run Terraform with your desired configuration:

### 1. Prepare your `terraform.tfvars` file

Here's an example:

```hcl
config-server = {
  app_name = "config-server"
  model    = "mongodb"
  constraints = "arch=amd64"
}

sharded = {
  app_name = "sharded"
  model    = "mongodb"
  constraints = "arch=amd64"
}

apps = [
  {
    app_name = "shard1"
    model    = "mongodb"
    config   = {
      role = "shard"
    }
    channel     = "6/stable"
    base        = "ubuntu@22.04"
    revision    = "199"
    units       = 3
    constraints = "arch=amd64"
    machines    = []
    storage     = {}
    endpoint_bindings = {}
    expose      = false
  }
]

data-integrator = {
  constraints = "arch=amd64"
  config = {
    "index-name"        = "test"
    "extra-user-roles"  = "admin"
    "database-name"     = "test-database"
  }
}

backups-integrator = {
  config = {
    "bucket" = "bruv"
  }
  constraints = "arch=amd64"
}

self-signed-certificates = {
  constraints = "arch=amd64"
}
```

### 2. Apply and initialize 

```bash
terraform init
terraform apply -var-file="terraform.tfvars"
```

