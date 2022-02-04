# Charmed MongoDB Operator


## Description

The Charmed MongoDB Operator delivers automated operations management from day 0 to day 2 on the [MongoDB Community Edition](https://github.com/mongodb/mongo) document database.

MongoDB is a general purpose distributed document database. This operator charm deploys and operates MongoDB on physical or virtual machines as a single replica.


## Usage

Until the MongoDB Machine Charm is published, you need to follow the build & deploy instructions from [CONTRIBUTING.md](https://github.com/canonical/mongodb-operator/blob/main/CONTRIBUTING.md) to deploy the charm.

After building the charm you may deploy a single unit of MongoDB using its default configuration
```shell
juju deploy ./*.charm
```

It is customary to use MongoDB with replication. Hence usually more than one unit (preferably and odd number) is deployed. To deploy MongoDB with multiple replicas specify the number of desired units with the `-n` option.
```shell
juju deploy ./*.charm -n <number of replicas>
```


## Relations

Supported [relations](https://juju.is/docs/olm/relations):

There are currently no supported relations.


## License
The Charmed MongoDB Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/mongodb-operator/blob/main/LICENSE) for more information.


## Security
Security issues in the Charmed MongoDB Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/mongodb-operator/blob/main/CONTRIBUTING.md) for developer guidance.
