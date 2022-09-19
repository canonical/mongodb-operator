# Charmed MongoDB Operator


## Description

The Charmed MongoDB Operator delivers automated operations management from day 0 to day 2 on the [MongoDB Community Edition](https://github.com/mongodb/mongo) document database.

MongoDB is a general purpose distributed document database. This operator charm deploys and operates MongoDB (vs 5.0) on physical or virtual machines as a single replica.


## Usage

### Basic Usage
To deploy a single unit of MongoDB using its default configuration
```shell
juju deploy mongodb --channel dpe/edge
```

It is customary to use MongoDB with replication. Hence usually more than one unit (preferably an odd number to prohibit a "split-brain" scenario) is deployed. To deploy MongoDB with multiple replicas, specify the number of desired units with the `-n` option.
```shell
juju deploy mongodb --channel dpe/edge -n <number_of_replicas>
```

To retrieve primary replica one can use the action `get-primary` on any of the units running MongoDB
```shell
juju run-action mongodb/<unit_number> get-primary --wait
```

Similarly, the primary replica is displayed as a status message in `juju status`, however one should note that this hook gets called on regular time intervals and the primary may be outdated if the status hook has not been called recently. 

### Replication
#### Adding Replicas
To add more replicas one can use the `juju add-unit` functionality i.e.
```shell
juju add-unit mongodb -n <num_of_replicas_to_add>
```
The implementation of `add-unit` allows the operator to add more than one unit, but functions internally by adding one replica at a time, as specified by the [constraints](https://www.mongodb.com/docs/manual/reference/command/replSetReconfig/#reconfiguration-can-add-or-remove-no-more-than-one-voting-member-at-a-time) of MongoDB.


#### Removing Replicas 
Similarly to scale down the number of replicas the `juju remove-unit` functionality may be used i.e.
```shell
juju remove-unit <name_of_unit1> <name_of_unit2>
```
The implementation of `remove-unit` allows the operator to remove more than one replica so long has the operator **does not remove a majority of the replicas**. The functionality of `remove-unit` functions by removing one replica at a time, as specified by the [constraints](https://www.mongodb.com/docs/manual/reference/command/replSetReconfig/#reconfiguration-can-add-or-remove-no-more-than-one-voting-member-at-a-time) of MongoDB.


## Relations

Supported [relations](https://juju.is/docs/olm/relations):

#### New `mongodb_client` interface:

Relations to new applications are supported via the `mongodb_client` interface. To create a relation: 

```shell
juju relate mongodb application
```

To remove a relation:
```shell
juju remove-relation mongodb application
```

#### Legacy `mongodb` interface:
We have also added support for the database legacy relation from the [original version](https://launchpad.net/charm-mongodb) of the charm via the `mongodb` interface. Currently legacy relations operate without authentication and hence cannot be used with pre-existing new relations. Please note that these relations will be deprecated.
 ```shell
juju relate mongodb graylog
```

#### `tls` interface:

We have also supported TLS for the MongoDB k8s charm. To enable TLS:

```shell
# deploy the TLS charm 
juju deploy tls-certificates-operator --channel=edge
# add the necessary configurations for TLS
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Test CA" 
# enable TLS via relation
juju relate tls-certificates-operator mongodb
# disable TLS by removing relation
juju remove-relation mongodb tls-certificates-operator
```

Note: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm [here](https://charmhub.io/tls-certificates-operator)

## Security
Security issues in the Charmed MongoDB Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/mongodb-operator/blob/main/CONTRIBUTING.md) for developer guidance.


## License
The Charmed MongoDB Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/mongodb-operator/blob/main/LICENSE) for more information.


## Trademark notice
MongoDB' is a trademark or registered trademark of MongoDB Inc. Other trademarks are property of their respective owners.