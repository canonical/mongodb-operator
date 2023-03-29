# Get a Charmed MongoDB up and running

This is part of the [Charmed MongoDB Tutorial](/t/charmed-mongodb-tutorial/8061). Please refer to this page for more information and the overview of the content. 

## Deploy

To deploy Charmed MongoDB, all you need to do is run the following command, which will fetch the charm from [Charmhub](https://charmhub.io/mongodb?channel=dpe/edge) and deploy it to your model:
```shell
juju deploy mongodb --channel dpe/edge
```

Juju will now fetch Charmed MongoDB and begin deploying it to the LXD cloud. This process can take several minutes depending on how provisioned (RAM, CPU,etc) your machine is. You can track the progress by running:
```shell
juju status --watch 1s
```

This command is useful for checking the status of Charmed MongoDB and gathering information about the machines hosting Charmed MongoDB. Some of the helpful information it displays include IP addresses, ports, state, etc. The command updates the status of Charmed MongoDB every second and as the application starts you can watch the status and messages of Charmed MongoDB change. Wait until the application is ready - when it is ready, `juju status --watch 1s` will show:
```
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  11:24:30Z

App      Version  Status  Scale  Charm    Channel   Rev  Exposed  Message
mongodb           active      1  mongodb  dpe/edge   96  no

Unit        Workload  Agent  Machine  Public address  Ports      Message
mongodb/0*  active    idle   0        10.23.62.156    27017/tcp

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running
```
To exit the screen with `juju status --watch 1s`, enter `Ctrl+c`.

## Access MongoDB
> **!** *Disclaimer: this part of the tutorial accesses MongoDB via the `admin` user. **Do not** directly interface with the admin user in a production environment. In a production environment [always create a separate user](https://www.mongodb.com/docs/manual/tutorial/create-users/) and connect to MongoDB with that user instead. Later in the section covering Relations we will cover how to access MongoDB without the admin user.*

The first action most users take after installing MongoDB is accessing MongoDB. The easiest way to do this is via the MongoDB shell, with `mongosh`. You can read more about the MongoDB shell [here](https://www.mongodb.com/docs/mongodb-shell/). For this part of the Tutorial we will access MongoDB via  `mongosh`. Fortunately there is no need to install the Mongo shell, as `mongosh` is already installed on the units hosting the Charmed MongoDB application.

### MongoDB URI
Connecting to the database requires a Uniform Resource Identifier (URI), MongoDB expects a [MongoDB specific URI](https://www.mongodb.com/docs/manual/reference/connection-string/). The URI for MongoDB contains information which is used to authenticate us to the database. We use a URI of the format:
```shell
mongodb://<username>:<password>@<hosts>/<database name>?replicaSet=<replica set name>
```

Connecting via the URI requires that you know the values for `username`, `password`, `hosts`, `database name`, and the `replica set name`. We will show you how to retrieve the necessary fields and set them to environment variables. 

**Retrieving the username:** In this case, we are using the `admin` user to connect to MongoDB. Use `admin` as the username:
```shell
export DB_USERNAME="admin"
```

**Retrieving the password:** The password can be retrieved by running the `get-password` action on the Charmed MongoDB application:
```shell
juju run-action mongodb/leader get-password --wait
```
Running the command should output:
```yaml
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
Use the password under the result: `admin-password`:
```shell
export DB_PASSWORD=$(juju run-action mongodb/leader get-password --wait | grep admin-password|  awk '{print $2}')
```

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
Set the variable `HOST_IP` to the IP address for `mongodb/0`:
```shell
export HOST_IP=$(juju run --unit mongodb/0 -- hostname -I | xargs)
```

**Retrieving the database name:** In this case we are connecting to the `admin` database. Use `admin` as the database name. Once we access the database via the MongoDB URI, we will create a `test-db` database to store data.
```shell
export DB_NAME="admin"
```

**Retrieving the replica set name:** The replica set name is the name of the application on Juju hosting MongoDB. The application name in this tutorial is `mongodb`. Use `mongodb` as the replica set name. 
```shell
export REPL_SET_NAME="mongodb"
```

### Generate the MongoDB URI
Now that we have the necessary fields to connect to the URI, we can connect to MongoDB with `mongosh` via the URI. We can create the URI with:
```shell
export URI=mongodb://$DB_USERNAME:$DB_PASSWORD@$HOST_IP/$DB_NAME?replicaSet=$REPL_SET_NAME
```
Now view and save the output of the URI:
```shell
echo $URI
```

### Connect via MongoDB URI
As said earlier, `mongosh` is already installed in Charmed MongoDB. To access the unit hosting Charmed MongoDB, ssh into it:
```shell
juju ssh mongodb/0
```
*Note if at any point you'd like to leave the unit hosting Charmed MongoDB, enter* `exit`.

While `ssh`d into `mongodb/0`, we can access `mongosh`, using the URI that we saved in the step [Generate the MongoDB URI](#generate-the-mongodb-uri).
```shell
mongosh <saved URI>
```

You should now see:
```
Current Mongosh Log ID: 6389e2adec352d5447551ae0
Connecting to:    mongodb://<credentials>@10.23.62.156/admin?replicaSet=mongodb&appName=mongosh+1.6.1
Using MongoDB:    5.0.14
Using Mongosh:    1.6.1

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
```shell
use test-db
```
Now lets create a user called `testUser` with read/write access to the database `test-db` that we just created. Enter:
```shell
db.createUser({
  user: "testUser",
  pwd: "password",
  roles: [
    { role: "readWrite", db: "test-db" }
  ]
})
```
You can verify that you added the user correctly by entering the command `show users` into the mongo shell. This will output:
```json
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
Feel free to test out any other MongoDB commands. When you’re ready to leave the MongoDB shell you can just type `exit`. Once you've typed `exit` you will be back in the host of Charmed MongoDB (`mongodb/0`). Exit this host by once again typing `exit`. Now you will be in your original shell where you first started the tutorial; here you can interact with Juju and LXD. 

*Note: if you accidentally exit one more time you will leave your terminal session and all of the environment variables used in the URI will be removed. If this happens redefine these variables as described in the section that describes how to [create the MongoDB URI](#mongodb-uri).*