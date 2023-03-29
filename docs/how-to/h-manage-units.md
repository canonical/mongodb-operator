# How to deploy and manage units

## Basic Usage

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

## Replication

### Adding Replicas
To add more replicas one can use the `juju add-unit` functionality i.e.
```shell
juju add-unit mongodb -n <num_of_replicas_to_add>
```
The implementation of `add-unit` allows the operator to add more than one unit, but functions internally by adding one replica at a time, as specified by the [constraints](https://www.mongodb.com/docs/manual/reference/command/replSetReconfig/#reconfiguration-can-add-or-remove-no-more-than-one-voting-member-at-a-time) of MongoDB.


### Removing Replicas 
Similarly to scale down the number of replicas the `juju remove-unit` functionality may be used i.e.
```shell
juju remove-unit <name_of_unit1> <name_of_unit2>
```
The implementation of `remove-unit` allows the operator to remove more than one replica so long has the operator **does not remove a majority of the replicas**. The functionality of `remove-unit` functions by removing one replica at a time, as specified by the [constraints](https://www.mongodb.com/docs/manual/reference/command/replSetReconfig/#reconfiguration-can-add-or-remove-no-more-than-one-voting-member-at-a-time) of MongoDB.