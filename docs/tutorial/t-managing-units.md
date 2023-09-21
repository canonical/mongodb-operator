# Scale your Charmed MongoDB

This is part of the [Charmed MongoDB Tutorial](/t/charmed-mongodb-tutorial/8061). Please refer to this page for more information and the overview of the content. 

## Adding and Removing units

Replication is a popular feature of MongoDB; replicas copy data making a database highly available. This means the application can provide self-healing capabilities in case one MongoDB replica fails. 

> **!** *Disclaimer: this tutorial hosts replicas all on the same machine, this should not be done in a production environment. To enable high availability in a production environment, replicas should be hosted on different servers to [maintain isolation](https://canonical.com/blog/database-high-availability).*


### Add replicas
You can add two replicas to your deployed MongoDB application with:
```shell
juju add-unit mongodb -n 2
```

You can now watch the replica set add these replicas with: `juju status --watch 1s`. It usually takes several minutes for the replicas to be added to the replica set. You’ll know that all three replicas are ready when `juju status --watch 1s` reports:
```
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  14:42:04Z

App      Version  Status  Scale  Charm    Channel   Rev  Exposed  Message
mongodb           active      3  mongodb  dpe/edge   96  no       Primary

Unit        Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*  active    idle   0        10.23.62.156    27017/tcp  Primary
mongodb/1   active    idle   1        10.23.62.55     27017/tcp
mongodb/2   active    idle   2        10.23.62.243    27017/tcp

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  jammy       Running
1        started  10.23.62.55   juju-d35d30-1  jammy       Running
2        started  10.23.62.243  juju-d35d30-2  jammy       Running
```

You can trust that Charmed MongoDB added these replicas correctly. But if you wanted to verify the replicas got added correctly you could connect to MongoDB via `charmed-mongodb.mongosh`. Since your replica set has 2 additional hosts you will need to update the hosts in your URI. You can retrieve these host IPs with:
```shell
export HOST_IP_1=$(juju run --unit mongodb/1 -- hostname -I | xargs)
export HOST_IP_2=$(juju run --unit mongodb/2 -- hostname -I | xargs)
```

Then recreate the URI using your new hosts and reuse the `username`, `password`, `database name`, and `replica set name` that you previously used when you *first* connected to MongoDB:
```shell
export URI=mongodb://$DB_USERNAME:$DB_PASSWORD@$HOST_IP,$HOST_IP_1,$HOST_IP_2/$DB_NAME?replicaSet=$REPL_SET_NAME
```

Now view and save the output of the URI:
```shell
echo $URI
```

Like earlier we access `mongosh` by `ssh`ing into one of the Charmed MongoDB hosts:
```shell
juju ssh mongodb/0
```

While `ssh`d into `mongodb/0`, we can access `mongosh` with `charmed-mongodb.mongosh`, using our new URI that we saved above.
```shell
charmed-mongodb.mongosh <saved URI>
```

Now type `rs.status()` and you should see your replica set configuration. It should look something like this:
```json
{
  set: 'mongodb',
  date: ISODate("2023-09-21T10:19:56.666Z"),
  myState: 1,
  term: Long("8"),
  syncSourceHost: '',
  syncSourceId: -1,
  heartbeatIntervalMillis: Long("2000"),
  majorityVoteCount: 2,
  writeMajorityCount: 2,
  votingMembersCount: 3,
  writableVotingMembersCount: 3,
  optimes: {
    lastCommittedOpTime: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
    lastCommittedWallTime: ISODate("2023-09-21T10:19:53.387Z"),
    readConcernMajorityOpTime: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
    appliedOpTime: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
    durableOpTime: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
    lastAppliedWallTime: ISODate("2023-09-21T10:19:53.387Z"),
    lastDurableWallTime: ISODate("2023-09-21T10:19:53.387Z")
  },
  lastStableRecoveryTimestamp: Timestamp({ t: 1695291546, i: 2 }),
  electionCandidateMetrics: {
    lastElectionReason: 'electionTimeout',
    lastElectionDate: ISODate("2023-09-21T09:57:28.251Z"),
    electionTerm: Long("8"),
    lastCommittedOpTimeAtElection: { ts: Timestamp({ t: 0, i: 0 }), t: Long("-1") },
    lastSeenOpTimeAtElection: { ts: Timestamp({ t: 1695290223, i: 4 }), t: Long("7") },
    numVotesNeeded: 2,
    priorityAtElection: 1,
    electionTimeoutMillis: Long("10000"),
    numCatchUpOps: Long("0"),
    newTermStartDate: ISODate("2023-09-21T09:57:28.258Z"),
    wMajorityWriteAvailabilityDate: ISODate("2023-09-21T09:57:28.810Z")
  },
  members: [
    {
      _id: 0,
      name: '10.165.186.135:27017',
      health: 1,
      state: 1,
      stateStr: 'PRIMARY',
      uptime: 1371,
      optime: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
      optimeDate: ISODate("2023-09-21T10:19:53.000Z"),
      lastAppliedWallTime: ISODate("2023-09-21T10:19:53.387Z"),
      lastDurableWallTime: ISODate("2023-09-21T10:19:53.387Z"),
      syncSourceHost: '',
      syncSourceId: -1,
      infoMessage: '',
      electionTime: Timestamp({ t: 1695290248, i: 1 }),
      electionDate: ISODate("2023-09-21T09:57:28.000Z"),
      configVersion: 5,
      configTerm: 8,
      self: true,
      lastHeartbeatMessage: ''
    },
    {
      _id: 1,
      name: '10.165.186.225:27017',
      health: 1,
      state: 2,
      stateStr: 'SECONDARY',
      uptime: 1351,
      optime: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
      optimeDurable: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
      optimeDate: ISODate("2023-09-21T10:19:53.000Z"),
      optimeDurableDate: ISODate("2023-09-21T10:19:53.000Z"),
      lastAppliedWallTime: ISODate("2023-09-21T10:19:53.387Z"),
      lastDurableWallTime: ISODate("2023-09-21T10:19:53.387Z"),
      lastHeartbeat: ISODate("2023-09-21T10:19:56.298Z"),
      lastHeartbeatRecv: ISODate("2023-09-21T10:19:55.325Z"),
      pingMs: Long("0"),
      lastHeartbeatMessage: '',
      syncSourceHost: '10.165.186.135:27017',
      syncSourceId: 0,
      infoMessage: '',
      configVersion: 5,
      configTerm: 8
    },
    {
      _id: 2,
      name: '10.165.186.179:27017',
      health: 1,
      state: 2,
      stateStr: 'SECONDARY',
      uptime: 1351,
      optime: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
      optimeDurable: { ts: Timestamp({ t: 1695291593, i: 4 }), t: Long("8") },
      optimeDate: ISODate("2023-09-21T10:19:53.000Z"),
      optimeDurableDate: ISODate("2023-09-21T10:19:53.000Z"),
      lastAppliedWallTime: ISODate("2023-09-21T10:19:53.387Z"),
      lastDurableWallTime: ISODate("2023-09-21T10:19:53.387Z"),
      lastHeartbeat: ISODate("2023-09-21T10:19:56.602Z"),
      lastHeartbeatRecv: ISODate("2023-09-21T10:19:55.344Z"),
      pingMs: Long("0"),
      lastHeartbeatMessage: '',
      syncSourceHost: '10.165.186.135:27017',
      syncSourceId: 0,
      infoMessage: '',
      configVersion: 5,
      configTerm: 8
    }
  ],
  ok: 1,
  '$clusterTime': {
    clusterTime: Timestamp({ t: 1695291593, i: 4 }),
    signature: {
      hash: Binary.createFromBase64("HiSmynKsjpsdvfJFZemY8q75KVs=", 0),
      keyId: Long("7281212693464219655")
    }
  },
  operationTime: Timestamp({ t: 1695291593, i: 4 })
}
```

Now exit the MongoDB shell by typing:
```shell
exit
```
Now you should be back in the host of Charmed MongoDB (`mongodb/0`). To exit this host type:
```shell
exit
```
You should now be shell you started in where you can interact with Juju and LXD.

### Remove replicas
Removing a unit from the application, scales the replicas down. Before we scale down the replicas, list all the units with `juju status`, here you will see three units `mongodb/0`, `mongodb/1`, and `mongodb/2`. Each of these units hosts a MongoDB replica. To remove the replica hosted on the unit `mongodb/2` enter:
```shell
juju remove-unit mongodb/2
```

You’ll know that the replica was successfully removed when `juju status --watch 1s` reports:
```
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  14:44:25Z

App      Version  Status  Scale  Charm    Channel   Rev  Exposed  Message
mongodb           active      2  mongodb  dpe/edge   96  no       Primary

Unit        Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*  active    idle   0        10.23.62.156    27017/tcp  Primary
mongodb/1   active    idle   1        10.23.62.55     27017/tcp

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  jammy       Running
1        started  10.23.62.55   juju-d35d30-1  jammy       Running

```

As previously mentioned you can trust that Charmed MongoDB removed this replica correctly. This can be checked by verifying that the new URI (where the removed host has been excluded) works properly.
