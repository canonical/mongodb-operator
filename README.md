# Charmed MongoDB Operator


## Description

The Charmed MongoDB Operator delivers automated operations management from day 0 to day 2 on the [MongoDB Community Edition](https://github.com/mongodb/mongo) document database.

MongoDB is a general purpose distributed document database. This operator charm deploys and operates MongoDB (vs 5.0) on physical or virtual machines as a single replica.

## Requirements 
- 2GB of RAM.
- 2 CPU threads per host.
- For production deployment: at least 60GB of available storage on each host. (Note if this is a test deployment: 5GB is sufficient for each host).
- Access to the internet for downloading the charm.
- Machine is running Ubuntu 20.04(focal) or later.

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

Further we highly suggest configuring the status hook to run frequently. In addition to reporting the primary, secondaries, and other statuses, the status hook performs self healing in the case of a network cut. To change the frequency of the update status hook do:
```shell
juju model-config update-status-hook-interval=<time(s/m/h)>
```
Note that this hook executes a read query to MongoDB. On a production level server this should be configured to occur at a frequency that doesn't overload the server with read requests. Similarly the hook should not be configured at too quick of a frequency as this can delay other hooks from running. You can read more about status hooks [here](https://juju.is/docs/sdk/update-status-event).

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
# to enable TLS relate the two applications 
juju relate tls-certificates-operator mongodb
```

Updates to private keys for certificate signing requests (CSR) can be made via the `set-tls-private-key` action. Note passing keys to external/internal keys should *only be done with* `base64 -w0` *not* `cat`. With three replicas this schema should be followed:
```shell
# generate shared internal key
openssl genrsa -out internal-key.pem 3072
# generate external keys for each unit
openssl genrsa -out external-key-0.pem 3072
openssl genrsa -out external-key-1.pem 3072
openssl genrsa -out external-key-2.pem 3072
# apply both private keys on each unit, shared internal key will be allied only on juju leader
juju run-action mongodb/0 set-tls-private-key "external-key=$(base64 -w0 external-key-0.pem)"  "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action mongodb/1 set-tls-private-key "external-key=$(base64 -w0 external-key-1.pem)"  "internal-key=$(base64 -w0 internal-key.pem)"  --wait
juju run-action mongodb/2 set-tls-private-key "external-key=$(base64 -w0 external-key-2.pem)"  "internal-key=$(base64 -w0 internal-key.pem)"  --wait

# updates can also be done with auto-generated keys with
juju run-action mongodb/0 set-tls-private-key --wait
juju run-action mongodb/1 set-tls-private-key --wait
juju run-action mongodb/2 set-tls-private-key --wait
```

To disable TLS remove the relation
```shell
juju remove-relation mongodb tls-certificates-operator
```

Note: The TLS settings here are for self-signed-certificates which are not recommended for production clusters, the `tls-certificates-operator` charm offers a variety of configurations, read more on the TLS charm [here](https://charmhub.io/tls-certificates-operator)

### Password rotation
#### Internal admin user
The admin user is used internally by the Charmed MongoDB Operator, the `set-admin-password` action can be used to rotate its password.
```shell
# to set a specific password for the admin user
juju run-action mongodb/leader set-admin-password password=<password> --wait

# to randomly generate a password for the admin user
juju run-action mongodb/leader set-admin-password --wait
```

#### Related applications users
To rotate the passwords of users created for related applications, the relation should be removed and related again. That process will generate a new user and password for the application.
```shell
juju remove-relation application mongodb
juju add-relation application mongodb
```

## Security
Security issues in the Charmed MongoDB Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/mongodb-operator/blob/main/CONTRIBUTING.md) for developer guidance.


## License
The Charmed MongoDB Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/mongodb-operator/blob/main/LICENSE) for more information.


## Trademark notice
MongoDB' is a trademark or registered trademark of MongoDB Inc. Other trademarks are property of their respective owners.
