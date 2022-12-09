# Charmed MongoDB tutorial:
Ready to try out Charmed MongoDB? This tutorial will guide you through the steps to get Charmed MongoDB up and running. 


## Minimum requirements:
Before we start be sure you have the following requirements:
- Ubuntu 20.04(focal) or later.
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.
- Access to the internet for downloading the required snaps and charms.


## Install and prepare LXD:
The fastest, simplest way to get started with Charmed MongoDB is to set up a local LXD cloud. LXD is a system container and virtual machine manager; Charmed MongoDB will be run in one of these containers and managed by Juju. While this tutorial covers the basics of LXD, you can explore more LXD [here](https://linuxcontainers.org/lxd/getting-started-cli/). The first step on our journey is to install LXD. LXD is installed from a snap package:
```
sudo snap install lxd --classic
```

Next we need to run `lxd init` to perform post-installation tasks. For this tutorial the default parameters are preferred and the network bridge should be set to have no ipv6 addresses:
```
lxd init --auto
lxc network set lxdbr0 ipv6.address none 
```

In the next step we will install Juju. Juju speaks directly to the local LXD daemon, which also requires [lxd group membership](https://linuxcontainers.org/lxd/getting-started-cli/#access-control). Add `$USER` to the group lxd:
```
newgrp lxd
sudo adduser $USER lxd
```

You can list all LXD containers by entering the command `lxc list` in to the command line. Although at this point in the tutorial none should exist and you'll only see this as output:
```
+------+-------+------+------+------+-----------+
| NAME | STATE | IPV4 | IPV6 | TYPE | SNAPSHOTS |
+------+-------+------+------+------+-----------+
```


## Install and prepare Juju:
[Juju](https://juju.is/) is an operation Lifecycle manager(OLM) for clouds, bare metal, LXD or Kubernetes. We will be using it to deploy and manage Charmed MongoDB. As with LXD, Juju is installed from a snap package:
```
sudo snap install juju --classic
```

Juju already has a built-in knowledge of LXD and how it works, so there is no additional setup or configuration needed. A controller will be used to deploy and control Charmed MongoDB. All we need to do is run the command to bootstrap a Juju controller named ‘overlord’ to LXD. 
```
juju bootstrap localhost overlord
```

The Juju controller should exist within an LXD container. You can verify this by entering the command `lxc list` and you should see the following:
```
+---------------+---------+-----------------------+------+-----------+-----------+
|     NAME      |  STATE  |         IPV4          | IPV6 |   TYPE    | SNAPSHOTS |
+---------------+---------+-----------------------+------+-----------+-----------+
| juju-<id>     | RUNNING | 10.105.164.235 (eth0) |      | CONTAINER | 0         |
+---------------+---------+-----------------------+------+-----------+-----------+
```
where `<id>` is a unique combination of numbers and letters such as `9d7e4e-0`

The controller can work with different models; models host applications such as Charmed MongoDB. Set up a specific model for Charmed MongoDB named ‘tutorial’:
```
juju add-model tutorial
```

You can now view the model you created above by entering the command `juju status` into the command line. You should see the following:
```
Model    Controller  Cloud/Region         Version  SLA          Timestamp
tutorial overlord    localhost/localhost  2.9.37   unsupported  23:20:53Z

Model "admin/tutorial" is empty.
```


## Deploying Charmed MongoDB:
To deploy Charmed MongoDB, fetch the charm from [Charmhub](https://charmhub.io/mongodb?channel=dpe/edge) and deploy it to your model:
```
juju deploy mongodb --channel dpe/edge
```

Juju will now fetch Charmed MongoDB and begin deploying it to the LXD cloud. This process can take several minutes depending on how provisioned your machine is. You can track the progress by running:
```
watch -c juju status --color
```

This will show charmed MongoDB along with its current status and other helpful information.

Wait until the application is ready, when it is ready `watch -c juju status --color` will show
```
Every 2.0s: juju status --color                                                                                         ip-172-31-11-104: Fri Dec  2 11:24:30 2022

Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  11:24:30Z

App      Version  Status  Scale  Charm    Channel   Rev  Exposed  Message
mongodb           active      1  mongodb  dpe/edge   96  no

Unit        Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*  active    idle   0        10.23.62.156    27017/tcp

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running
```

## Accessing MongoDB:
*Disclaimer: this part of the tutorial accesses MongoDB via the `admin` user. It is not recommended that you directly interface with the admin user in a production environment. In a production environment [create a separate user](https://www.mongodb.com/docs/manual/tutorial/create-users/) and connect to MongoDB with that user instead. Later in the section covering Relations we will cover how to access MongoDB without the admin user.
*

For this part of the Tutorial we will access MongoDB - via the MongoDB shell `mongosh`. You can read more about the MongoDB shell [here](https://www.mongodb.com/docs/mongodb-shell/).


### Install the MongoDB shell:
While MongoDB is installed within the LXD containers that the application is hosted on, it is not installed on your machine. This means that you will have to install the MongoDB shell yourself. Install `mongosh` by following the official [instructions on how to install the MongoDB shell](https://www.mongodb.com/docs/mongodb-shell/install/#std-label-mdb-shell-install).

### MongoDB URI:
Connecting to the database requires a [URI](https://www.mongodb.com/docs/manual/reference/connection-string/). We use a URI of the format:
```
mongodb://<username>:<password>@<hosts>/<database name>?replicaSet=<replica set name>
```

Connecting via the URI requires that you know the values for `username`, `password`, `hosts`, `database name`, and the `replica set name`. We will show you how to retrieve the necessary fields. 

**Retrieving the username:** In this case, we are using the `admin` user to connect to MongoDB. Use `admin` as the username.

**Retrieving the password:** The password can be retrieved by running the `get-admin-password` action on the Charmed MongoDB application:
```
juju run-action mongodb/leader get-admin-password --wait
```
Running the command should output:
```
unit-mongodb-0:
  UnitId: mongodb/0
  id: "2"
  results:
    admin-password: <password>
  status: completed
  timing:
    completed: 2022-12-02 11:30:01 +0000 UTC
    enqueued: 2022-12-02 11:29:57 +0000 UTC
    started: 2022-12-02 11:30:01 +0000 UTC
```
Use the password under the result: `admin-password`.

**Retrieving the hosts:** The hosts are the units hosting the MongoDB application. The host’s IP address can be found with `juju status`:

```
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  11:31:16Z

App      Version  Status  Scale  Charm    Channel   Rev  Exposed  Message
mongodb           active      1  mongodb  dpe/edge   96  no       Replica set primary

Unit        Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*  active    idle   0        <host IP>    27017/tcp  Replica set primary

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running

```
Use the IP address listed underneath `Public address` for `mongodb/0` as your host.

**Retrieving the database name:** In this case we are connecting to the `admin` database. Use `admin` as the database name. Once we access the database via the MongoDB URI, we will create a `test-db` database to store data.

**Retrieving the replica set name:** The replica set name is the name of the application on Juju hosting MongoDB. The application name in this tutorial is `mongodb`. Use `mongodb` as the replica set name. 

### Connect via MongoDB URI:
Now that we have the necessary fields to connect to the URI, we can connect to MongoDB via the URI. Enter the following into the command line, replace the values for  `username`, `password`, `hosts`, `database name`, and the `replica set name` with what you’ve retrieved above:
```
mongosh mongodb://<username>:<password>@<host>/<database name>?replicaSet=<replica set name>
```

You should now see:
```
Current Mongosh Log ID:	6389e2adec352d5447551ae0
Connecting to:		mongodb://<credentials>@10.23.62.156/admin?replicaSet=mongodb&appName=mongosh+1.6.1
Using MongoDB:		5.0.14
Using Mongosh:		1.6.1

For mongosh info see: https://docs.mongodb.com/mongodb-shell/


To help improve our products, anonymous usage data is collected and sent to MongoDB periodically (https://www.mongodb.com/legal/privacy-policy).
You can opt-out by running the disableTelemetry() command.

------
   The server generated these startup warnings when booting
   2022-12-02T11:24:05.416+00:00: Using the XFS filesystem is strongly recommended with the WiredTiger storage engine. See http://dochub.mongodb.org/core/prodnotes-filesystem
------

------
   Enable MongoDB's free cloud-based monitoring service, which will then receive and display
   metrics about your deployment (disk utilization, CPU, operation statistics, etc).

   The monitoring data will be available on a MongoDB website with a unique URL accessible to you
   and anyone you share the URL with. MongoDB may use this information to make product
   improvements and to suggest MongoDB products and deployment options to you.

   To enable free monitoring, run the following command: db.enableFreeMonitoring()
   To permanently disable this reminder, run the following command: db.disableFreeMonitoring()
------

mongodb [primary] admin>
```

You can now interact with MongoDB directly using any [MongoDB commands](https://www.mongodb.com/docs/manual/reference/command/). For example entering `show dbs` should output something like:
```
admin   172.00 KiB
config  120.00 KiB
local   404.00 KiB
```
Now that we have access to MongoDB we can create a database named `test-db`. To create this database enter:
```
use test-db
```
Now lets create a user called `testUser` read/write access to the database `test-db` that we just created . Enter:
```
db.createUser({
  user: "testUser",
  pwd: "password",
  roles: [
    { role: "readWrite", db: "test-db" }
  ]
})
```
You can verify that you added the user correctly, by entering the command `show users` into the mongo shell, this will output:
```
[
  {
    _id: 'test-db.testUser',
    userId: new UUID("6e841e28-b1bc-4719-bf42-ba4b164fc546"),
    user: 'testUser',
    db: 'test-db',
    roles: [ { role: 'readWrite', db: 'test-db' } ],
    mechanisms: [ 'SCRAM-SHA-1', 'SCRAM-SHA-256' ]
  }
]
```
Feel free to test out any other MongoDB commands, when you’re ready to leave the shell you can just type `exit`.


## Scaling Charmed MongoDB: 
Replication is a popular feature of MongoDB; replicas copy data making a database highly available. 


### Add replicas:
You can add two replicas to your deployed MongoDB application with:
```
juju add-unit mongodb -n 2
```

You can now watch the replica set add these replicas with: `watch -c juju status --color`. You’ll know that all three replicas are ready when `watch -c juju status --color` reports:
```
Every 2.0s: juju status --color                                                                                                                                                ip-172-31-11-104: Fri Dec  2 14:36:50 2022

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

You can trust that Charmed MongoDB added these replicas correctly. But if you wanted to verify the replicas got added correctly you could connect to MongoDB via `mongosh`. Since your replica set has 2 additional hosts you will need to update the hosts in your URI. Using the IP addresses from `juju status` add all of your hosts to the URI and separate them with commas. Your URI should look like this:
```
mongodb://<username>:<password>@<host1,<host2>,<host3>>/<database name>?replicaSet=<replica set name>
```

Then connect with `mongosh`; using your new hosts and reuse the `username`, `password,` `database name`, and `replica set name` that you previously used when you *first* connected to MongoDB:
```
mongosh mongodb://<username>:<password>@<host1,<host2>,<host3>>/<database name>?replicaSet=<replica set name>
```

Now type `rs.status()` and you should see your replica set configuration. It should look something like this:
```
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

Now exit the shell by typing:
```
exit
```


### Remove replicas:
To remove a replica type:
```
juju remove-unit mongodb/2
```

You’ll know that the replica was successfully removed when `watch -c juju status --color` reports:
```
Every 2.0s: juju status --color                                                                                                                                                ip-172-31-11-104: Fri Dec  2 14:44:25 2022

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


## Passwords:
### Retrieving the admin password:
As previously mentioned, the admin password can be retrieved by running the `get-admin-password` action on the Charmed MongoDB application:
```
juju run-action mongodb/leader get-admin-password --wait
```
Running the command should output:
```
unit-mongodb-0:
  UnitId: mongodb/0
  id: "2"
  results:
    admin-password: <password>
  status: completed
  timing:
    completed: 2022-12-02 11:30:01 +0000 UTC
    enqueued: 2022-12-02 11:29:57 +0000 UTC
    started: 2022-12-02 11:30:01 +0000 UTC
```
The admin password is under the result: `admin-password`.


### Rotating the admin password
You can change the admin password to a new random password by entering:
```
juju run-action mongodb/leader set-admin-password --wait
```
Running the command should output:
```
unit-mongodb-0:
  UnitId: mongodb/0
  id: "4"
  results:
    admin-password: <new password>
  status: completed
  timing:
    completed: 2022-12-02 14:53:30 +0000 UTC
    enqueued: 2022-12-02 14:53:25 +0000 UTC
    started: 2022-12-02 14:53:28 +0000 UTC
```
The admin password is under the result: `admin-password`. It should be different from your previous password.

*Note when you change the admin password you will also need to update the admin password the in MongoDB URI; as the old password will no longer be valid*

### Setting the admin password
You can change the admin password to a specific password by entering:
```
juju run-action mongodb/leader set-admin-password password=<password> --wait
```
Running the command should output:
```
unit-mongodb-0:
  UnitId: mongodb/0
  id: "4"
  results:
    admin-password: <password>
  status: completed
  timing:
    completed: 2022-12-02 14:53:30 +0000 UTC
    enqueued: 2022-12-02 14:53:25 +0000 UTC
    started: 2022-12-02 14:53:28 +0000 UTC
```
The admin password under the result: `admin-password` should match whatever you passed in when you entered the command.

*Note when you change the admin password you will also need to update the admin password the in MongoDB URI; as the old password will no longer be valid*

## Relations
<!---Juju 3.0 uses integrations; I haven’t been able to find the docs for 2.9 --->
[Relations](https://juju.is/docs/sdk/integration) are the easiest way to create a user for MongoDB in Charmed MongoDB; relations automatically create a username, password, and database for the desired user/application. As mentioned earlier in the [Accessing MongoDB](#accessing-mongodb) it is a better practice to connect to MongoDB via a specific user rather than the admin user.

### Data Integrator Charm
Before relating to a charmed application, we must deploy our charmed application. In this tutorial we will relate to the [Data Integrator Charm](https://github.com/canonical/data-integrator). This is a bare-bones charm that allows for central management of database users, providing support for different kind of data platforms (e.g. MongoDB, MySQL, PostgreSQL, Kafka, etc) with a consistent, opinionated and robust user experience. In order to deploy the Data Integrator Charm we must clone its source code from GitHub and create the charm executable ourselves: 

<!--- note in the future replace this with juju deploy instead of from git --->
```
git clone https://github.com/canonical/data-integrator.git
cd data-integrator/
sudo snap install charmcraft --classic
charmcraft pack
```
After packing the charm, you can see that a charm executable named `database-integrator_ubuntu-22.04-amd64.charm` has been created in the `data-integrator` directory. When we deploy the charm we can also specify the name of the database that we want created in MongoDB with the `database` config option. To deploy this charm with juju and create a database in MongoDB named `test-database` enter:
```
juju deploy ./database-integrator_ubuntu-22.04-amd64.charm --config database=test-database
```

### Relating to MongoDB
Now that the Database Integrator Charm has been set up, we can relate it to MongoDB. This will automatically create a username, password, and database for the Database Integrator Charm. Relate the two applications with:
```
juju relate database-integrator mongodb
```
Wait for `watch -c juju status --color` to show:
```
ubuntu@ip-172-31-11-104:~/data-integrator$ juju status
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  10:32:09Z

App                  Version  Status  Scale  Charm                Channel   Rev  Exposed  Message
database-integrator           active      1  database-integrator              0  no       received mongodb credentials
mongodb                       active      2  mongodb              dpe/edge   96  no

Unit                    Workload  Agent  Machine  Public address  Ports      Message
database-integrator/0*  active    idle   5        10.23.62.216               received mongodb credentials
mongodb/0*              active    idle   0        10.23.62.156    27017/tcp
mongodb/1               active    idle   1        10.23.62.55     27017/tcp  Replica set primary

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running
1        started  10.23.62.55   juju-d35d30-1  focal       Running
5        started  10.23.62.216  juju-d35d30-5  jammy       Running
```
To retrieve information such as the username, password, and database. Enter:
```
juju run-action  database-integrator/0 get-credentials --wait
```
This should output something like:
```
​​unit-database-integrator-0:
  UnitId: database-integrator/0
  id: "24"
  results:
    mongodb:
      database: test-database
      endpoints: 10.23.62.55,10.23.62.156
      password: VMnRws6BlojzDi5e1m2GVWOgJaoSs44d
      replset: mongodb
      uris: mongodb://relation-4:VMnRws6BlojzDi5e1m2GVWOgJaoSs44d@10.23.62.55,10.23.62.156/test-database?replicaSet=mongodb&authSource=admin
      username: relation-4
    ok: "True"
  status: completed
  timing:
    completed: 2022-12-06 10:33:24 +0000 UTC
    enqueued: 2022-12-06 10:33:20 +0000 UTC
    started: 2022-12-06 10:33:24 +0000 UTC
```
*Note: your hostnames, usernames, and passwords will likely be different.*

### Accessing the related database:
Notice that in the previous step when you typed `juju run-action  database-integrator/0 get-credentials --wait` the command not only outputted the username, password, and database, but also outputted the URI. This means you do not have to generate the URI yourself. To connect to the database associated with the Database Integrator Charm enter:
```
mongosh "<uri from juju run-action  database-integrator/0 get-credentials --wait>"
```
*Note: be sure you wrap the URI in `"`*

You will now be in the mongo shell as the user created for this relation. When you relate two applications Charmed MongoDB automatically sets up a user and database for you. Enter `show dbs` into the MongoDB shell, this will output:
```
test-database  8.00 KiB
```
This is the name of the database we specified when we first deployed the `database-integrator` charm. To create a collection in the "test-database" and then show the collection enter:
```
db.createCollection("test-collection")
show collections
```
Now insert a document into this database:
```
db.test_collection.insertOne(
	{
		First_Name: "Jammy",
		Last_Name: "Jellyfish",
  })
```
You can verify this document was inserted by running:
```
db.test_collection.find()
```

Now exit the shell by typing `exit`

### Removing the user
To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:
```
juju remove-relation mongodb database-integrator
```

Now try again to connect to the same URI you just used in [Accessing the related database](#accessing-the-related-database):
```
mongosh "<uri from juju run-action  database-integrator/0 get-credentials --wait>"
```

This will output an error message:
```
Current Mongosh Log ID:	638f5ffbdbd9ec94c2e58456
Connecting to:		mongodb://<credentials>@10.23.62.38,10.23.62.219/mongodb?replicaSet=mongodb&authSource=admin&appName=mongosh+1.6.1
MongoServerError: Authentication failed.
```
As this user no longer exists. This is expected as `juju remove-relation mongodb database-integrator` also removes the user. 

If you wanted to recreate this user all you would need to do is relate the the two applications again:
```
juju relate database-integrator mongodb
```
Re-relating generates a new password for this user, and therefore a new URI you can see the new URI with `juju run-action  database-integrator/0 get-credentials --wait`. You can connect to the database with this new URI:
```
mongosh "<uri from juju run-action  database-integrator/0 get-credentials --wait>"
```
From there if you enter `db.test_collection.find()` you will see all of your original documents are still present in the database. 

## Transcript Layer Security (TLS)
[TLS](https://en.wikipedia.org/wiki/Transport_Layer_Security) is used to encrypt data exchanged between two applications; it secures data transmitted over the network. Typically enabling up TLS within a highly available database and between a highly available database and client/server applications, requires domain specific knowledge and a high level of expertise. Fortunately, the domain specific knowledge has been encoded into Charmed MongoDB. This means enabling TLS on Charmed MongoDB is readily available and requires minimal effort on your end.

Again, relations come in handy here as TLS is enabled via relations; i.e. by relating Charmed MongoDB to the [TLS Certificates Charm](https://charmhub.io/tls-certificates-operator). The TLS Certificates Charm centralises TLS certificate management in a consistent manner and handles providing, requesting, and renewing TLS certificates.


### Configure TLS
Before enabling TLS on Charmed MongoDB we must first deploy the `TLS-certificates-operator` charm:
```
juju deploy tls-certificates-operator --channel=edge
```

Wait until the `tls-certificates-operator` is ready to be configured. When it is ready to be configured `watch -c juju status --color`. Will show:
```
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  09:24:12Z

App                        Version  Status   Scale  Charm                      Channel   Rev  Exposed  Message
mongodb                             active       2  mongodb                    dpe/edge   96  no       Replica set primary
tls-certificates-operator           blocked      1  tls-certificates-operator  edge       16  no       Configuration options missing: ['certificate', 'ca-certificate']

Unit                          Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*                    active    idle   0        10.23.62.156    27017/tcp  Replica set primary
mongodb/1                     active    idle   1        10.23.62.55     27017/tcp  Replica set secondary
tls-certificates-operator/0*  blocked   idle   3        10.23.62.8                 Configuration options missing: ['certificate', 'ca-certificate']

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running
1        started  10.23.62.55   juju-d35d30-1  focal       Running
3        started  10.23.62.8    juju-d35d30-3  focal       Running
```

Now we can configure the TLS certificates. Configure the  `tls-certificates-operator` to use self signed certificates:
```
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Tutorial CA" 
```
*Note: this tutorial uses (self signed certificates)[https://en.wikipedia.org/wiki/Self-signed_certificate]; self signed certificates should not be used in a production cluster.*

### Enabling TLS:
After configuring the certificates `watch -c juju status --color` will show the status of `tls-certificates-operator` as active. To enable TLS on Charmed MongoDB, relate the two applications:
```
juju relate tls-certificates-operator mongodb
```

### Connecting to MongoDB with TLS:
Once TLS has been enabled we will need to change how we connect to MongoDB. Specifically we will need to specify the TLS CA file along with the TLS Certificate file. These are hosted on the Charmed MongoDB application. Copy them from Charmed MongoDB to your machine:
```
juju run --unit mongodb/0 -- cat /etc/mongodb/external-ca.crt > external-ca.crt
juju run --unit mongodb/0 -- cat /etc/mongodb/external-cert.pem > external-cert.pem
```

As before, we will connect to MongoDB via a MongoDB URI; use the admin user MongoDB URI that you first used to [connect to MongoDB](#connect-via-mongodb-uri). Connect using the URI and the following TLS options:
```
mongosh mongodb://<username>:<password>@<host1>/<database name>?replicaSet=<replica set name> --tls --tlsCAFile external-ca.crt --tlsCertificateKeyFile external-cert.pem
```

Congratulations, you've now connected to MongoDB with TLS. Now exit the shell by typing `exit`.

### Disabling TLS
To disable TLS unrelate the two applications:
```
juju remove-relation mongodb tls-certificates-operator
```
