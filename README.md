# MongoDB Operator


## Description

The MongoDB Operator provides a document database using [MongoDB](https://www.mongodb.com/).

MongoDB is a general purpose distributed document database. This charm deploys and operates MongoDB on a machine cloud.

This charm seeks to migrate the features from the current Mongo charm that uses the Reactive framework to the new Operator framework.


## Usage

As this charm is not yet published, you need to follow the build and deploy instructions from [CONTRIBUTING.md](./CONTRIBUTING.md).


## Relations

Supported relations:

- This charm supports peer relations, wich provides replica sets for the database.

The charm will implement both [sharding](https://docs.mongodb.com/manual/sharding/) and [replica set](https://docs.mongodb.com/manual/replication/). To do this, it will need an extra component, the `config-server`. Future relations will include:

- Mongo router `mongos` charm deployed alongside MongoDB charm. It will handle a sharded deployment, and it can work as a MongoDB database interface.
- A MongoDB database `shard` interface. It will be used by the mongos charm as well.
- A `config-server` interface used by the mongos charm.

## Contributing

TODO: update when charm is published