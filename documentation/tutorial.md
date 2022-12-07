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

#### Retrieving the username:
In this case, we are using the `admin` user to connect to MongoDB. Use `admin` as the username.

#### Retrieving the password:
The password can be retrieved by running the `get-admin-password` action on the Charmed MongoDB application:
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

#### Retrieving the hosts:
The hosts are the units hosting the MongoDB application. In this case we only have one host; you can find the host’s IP address with `juju status`. This will output information about the Charmed MongoDB application along with it’s IP address:
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

#### Retrieving the database name:
In this case we are logging in via the `admin` user so we will be connecting to the `admin` database. Use `admin` as the database name. Once we access the database via the MongoDB URI, we will create a `test-db` database to store data.

#### Retrieving the replica set name:
The replica set name is the name of the application. In this tutorial we didn’t use a custom name for the application, so the application name is `mongodb`. You can read more about deploying a charm with a custom name [here](https://juju.is/docs/olm/deploy-a-charm-from-charmhub#heading--override-the-name-of-a-deployed-application). Use `mongodb` as the replica set name.

### Connect via MongoDB URI:
Now that we have the necessary fields to connect to the URI, we can connect to MongoDB via the URI. Enter the following into the command line, replace the values for  `username`, `password`, `hosts`, `database name`, and the `replica set name` with what you’ve retrieved above:
```
mongosh mongodb://<username>:<password>@<hosts>/<database name>?replicaSet=<replica set name>
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
