# How to manage related applications

## New `mongodb_client` interface:

Relations to new applications are supported via the `mongodb_client` interface. To create a relation: 

```shell
juju relate mongodb application
```

To remove a relation:

```shell
juju remove-relation mongodb application
```

## Legacy `mongodb` interface:

We have also added support for the database legacy relation from the [original version](https://launchpad.net/charm-mongodb) of the charm via the `mongodb` interface. Currently legacy relations operate without authentication and hence cannot be used with pre-existing new relations. Please note that these relations will be deprecated.

 ```shell
juju relate mongodb graylog
```

## Rotate applications password

To rotate the passwords of users created for related applications, the relation should be removed and related again. That process will generate a new user and password for the application.

```shell
juju remove-relation application mongodb
juju add-relation application mongodb
```

### Internal operator user

The operator user is used internally by the Charmed MongoDB Operator, the `set-password` action can be used to rotate its password.

* To set a specific password for the operator user

```shell
juju run-action mongodb/leader set-password password=<password> --wait
```

* To randomly generate a password for the operator user

```
juju run-action mongodb/leader set-password --wait
```