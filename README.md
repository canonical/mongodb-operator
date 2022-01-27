# Charmed MongoDB Operator


## Description

The Charmed MongoDB Operator delivers automated operations management from day 0 to day 2 on the [MongoDB Community Edition](https://github.com/mongodb/mongo) document database.

MongoDB is a general purpose distributed document database. This operator charm deploys and operates MongoDB on physical or virtual machines as a single replica.


## Usage

Until the MongoDB Machine Charm is published, you need to follow the build & deploy instructions from [CONTRIBUTING.md](./CONTRIBUTING.md) to deploy the charm.


## Relations

Supported [relations](https://juju.is/docs/olm/relations):

- This charm supports peer relations, which provides replica sets for the database.

The charm will implement both [sharding](https://docs.mongodb.com/manual/sharding/) and [replica set](https://docs.mongodb.com/manual/replication/). To do this, it will need an extra component, the `config-server`.

Future relations will include:

- Mongo router `mongos` charm deployed alongside MongoDB charm. It will handle a sharded deployment, and it can work as a MongoDB database interface.
- A MongoDB database `shard` interface. It will be used by the mongos charm as well.
- A `config-server` interface used by the mongos charm.

## Contributing

TODO: update when charm is published