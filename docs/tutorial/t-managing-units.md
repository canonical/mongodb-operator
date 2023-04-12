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
mongodb           active      3  mongodb  dpe/edge   96  no       Replica set primary

Unit        Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*  active    idle   0        10.23.62.156    27017/tcp  Replica set primary
mongodb/1   active    idle   1        10.23.62.55     27017/tcp  Replica set secondary
mongodb/2   active    idle   2        10.23.62.243    27017/tcp  Replica set secondary

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running
1        started  10.23.62.55   juju-d35d30-1  focal       Running
2        started  10.23.62.243  juju-d35d30-2  focal       Running
```

You can trust that Charmed MongoDB added these replicas correctly. But if you wanted to verify the replicas got added correctly you could connect to MongoDB via `mongosh`. Since your replica set has 2 additional hosts you will need to update the hosts in your URI. You can retrieve these host IPs with:
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

While `ssh`d into `mongodb/0`, we can access `mongosh`, using our new URI that we saved above.
```shell
mongosh <saved URI>
```

Now type `rs.status()` and you should see your replica set configuration. It should look something like this:
```json
{
  set: 'mongodb',
  date: ISODate("2022-12-02T14:39:52.732Z"),
  myState: 1,
  term: Long("1"),
  syncSourceHost: '',
  syncSourceId: -1,
  heartbeatIntervalMillis: Long("2000"),
  majorityVoteCount: 2,
  writeMajorityCount: 2,
  votingMembersCount: 3,
  writableVotingMembersCount: 3,
  optimes: {
    lastCommittedOpTime: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
    lastCommittedWallTime: ISODate("2022-12-02T14:39:50.020Z"),
    readConcernMajorityOpTime: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
    appliedOpTime: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
    durableOpTime: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
    lastAppliedWallTime: ISODate("2022-12-02T14:39:50.020Z"),
    lastDurableWallTime: ISODate("2022-12-02T14:39:50.020Z")
  },
  lastStableRecoveryTimestamp: Timestamp({ t: 1669991950, i: 1 }),
  electionCandidateMetrics: {
    lastElectionReason: 'electionTimeout',
    lastElectionDate: ISODate("2022-12-02T11:24:09.587Z"),
    electionTerm: Long("1"),
    lastCommittedOpTimeAtElection: { ts: Timestamp({ t: 1669980249, i: 1 }), t: Long("-1") },
    lastSeenOpTimeAtElection: { ts: Timestamp({ t: 1669980249, i: 1 }), t: Long("-1") },
    numVotesNeeded: 1,
    priorityAtElection: 1,
    electionTimeoutMillis: Long("10000"),
    newTermStartDate: ISODate("2022-12-02T11:24:09.630Z"),
    wMajorityWriteAvailabilityDate: ISODate("2022-12-02T11:24:09.651Z")
  },
  members: [
    {
      _id: 0,
      name: '10.23.62.156:27017',
      health: 1,
      state: 1,
      stateStr: 'PRIMARY',
      uptime: 11747,
      optime: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
      optimeDate: ISODate("2022-12-02T14:39:50.000Z"),
      lastAppliedWallTime: ISODate("2022-12-02T14:39:50.020Z"),
      lastDurableWallTime: ISODate("2022-12-02T14:39:50.020Z"),
      syncSourceHost: '',
      syncSourceId: -1,
      infoMessage: '',
      electionTime: Timestamp({ t: 1669980249, i: 2 }),
      electionDate: ISODate("2022-12-02T11:24:09.000Z"),
      configVersion: 5,
      configTerm: 1,
      self: true,
      lastHeartbeatMessage: ''
    },
    {
      _id: 1,
      name: '10.23.62.55:27017',
      health: 1,
      state: 2,
      stateStr: 'SECONDARY',
      uptime: 305,
      optime: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
      optimeDurable: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
      optimeDate: ISODate("2022-12-02T14:39:50.000Z"),
      optimeDurableDate: ISODate("2022-12-02T14:39:50.000Z"),
      lastAppliedWallTime: ISODate("2022-12-02T14:39:50.020Z"),
      lastDurableWallTime: ISODate("2022-12-02T14:39:50.020Z"),
      lastHeartbeat: ISODate("2022-12-02T14:39:51.868Z"),
      lastHeartbeatRecv: ISODate("2022-12-02T14:39:51.882Z"),
      pingMs: Long("0"),
      lastHeartbeatMessage: '',
      syncSourceHost: '10.23.62.156:27017',
      syncSourceId: 0,
      infoMessage: '',
      configVersion: 5,
      configTerm: 1
    },
    {
      _id: 2,
      name: '10.23.62.243:27017',
      health: 1,
      state: 2,
      stateStr: 'SECONDARY',
      uptime: 300,
      optime: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
      optimeDurable: { ts: Timestamp({ t: 1669991990, i: 1 }), t: Long("1") },
      optimeDate: ISODate("2022-12-02T14:39:50.000Z"),
      optimeDurableDate: ISODate("2022-12-02T14:39:50.000Z"),
      lastAppliedWallTime: ISODate("2022-12-02T14:39:50.020Z"),
      lastDurableWallTime: ISODate("2022-12-02T14:39:50.020Z"),
      lastHeartbeat: ISODate("2022-12-02T14:39:51.861Z"),
      lastHeartbeatRecv: ISODate("2022-12-02T14:39:52.372Z"),
      pingMs: Long("0"),
      lastHeartbeatMessage: '',
      syncSourceHost: '10.23.62.55:27017',
      syncSourceId: 1,
      infoMessage: '',
      configVersion: 5,
      configTerm: 1
    }
  ],
  ok: 1,
  '$clusterTime': {
    clusterTime: Timestamp({ t: 1669991990, i: 1 }),
    signature: {
      hash: Binary(Buffer.from("dbe96e73cf659617bb88b6ad11152551c0dd9c8d", "hex"), 0),
      keyId: Long("7172510554420936709")
    }
  },
  operationTime: Timestamp({ t: 1669991990, i: 1 })
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
mongodb           active      2  mongodb  dpe/edge   96  no       Replica set primary

Unit        Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*  active    idle   0        10.23.62.156    27017/tcp  Replica set primary
mongodb/1   active    idle   1        10.23.62.55     27017/tcp  Replica set secondary

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running
1        started  10.23.62.55   juju-d35d30-1  focal       Running

```

As previously mentioned you can trust that Charmed MongoDB removed this replica correctly. This can be checked by verifying that the new URI (where the removed host has been excluded) works properly.