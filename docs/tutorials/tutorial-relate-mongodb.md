# Relate your MongoDB deployment 

This is part of the [Charmed MongoDB Tutorial](/t/charmed-mongodb-tutorial/8061). Please refer to this page for more information and the overview of the content. 

## Relations
<!---Juju 3.0 uses integrations; I haven’t been able to find the docs for 2.9 --->
Relations, or what Juju documentation [describes as Integration](https://juju.is/docs/sdk/integration), are the easiest way to create a user for MongoDB in Charmed MongoDB. Relations automatically create a username, password, and database for the desired user/application. As mentioned earlier in the [Access MongoDB section](#access-mongodb) it is a better practice to connect to MongoDB via a specific user rather than the admin user.

### Data Integrator Charm
Before relating to a charmed application, we must first deploy our charmed application. In this tutorial we will relate to the [Data Integrator Charm](https://charmhub.io/data-integrator). This is a bare-bones charm that allows for central management of database users, providing support for different kinds of data platforms (e.g. MongoDB, MySQL, PostgreSQL, Kafka, etc) with a consistent, opinionated and robust user experience. In order to deploy the Data Integrator Charm we can use the command `juju deploy` we have learned above:

```shell
juju deploy data-integrator --channel edge --config database-name=test-database
```
The expected output:
```
Located charm "data-integrator" in charm-hub, revision 3
Deploying "data-integrator" from charm-hub charm "data-integrator", revision 3 in channel edge on jammy
```

### Relate to MongoDB
Now that the Database Integrator Charm has been set up, we can relate it to MongoDB. This will automatically create a username, password, and database for the Database Integrator Charm. Relate the two applications with:
```shell
juju relate data-integrator mongodb
```
Wait for `juju status --watch 1s` to show:
```
ubuntu@ip-172-31-11-104:~/data-integrator$ juju status
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  overlord    localhost/localhost  2.9.37   unsupported  10:32:09Z

App                  Version  Status  Scale  Charm                Channel   Rev  Exposed  Message
data-integrator               active      1  data-integrator      edge       3   no
mongodb                       active      2  mongodb              dpe/edge   96  no

Unit                    Workload  Agent  Machine  Public address  Ports      Message
data-integrator/0*  active    idle   5        10.23.62.216               received mongodb credentials
mongodb/0*              active    idle   0        10.23.62.156    27017/tcp
mongodb/1               active    idle   1        10.23.62.55     27017/tcp  Replica set primary

Machine  State    Address       Inst id        Series  AZ  Message
0        started  10.23.62.156  juju-d35d30-0  focal       Running
1        started  10.23.62.55   juju-d35d30-1  focal       Running
5        started  10.23.62.216  juju-d35d30-5  jammy       Running
```
To retrieve information such as the username, password, and database. Enter:
```shell
juju run-action data-integrator/leader get-credentials --wait
```
This should output something like:
```yaml
​​unit-data-integrator-0:
  UnitId: data-integrator/0
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
Save the value listed under `uris:` *(Note: your hostnames, usernames, and passwords will likely be different.)*

### Access the related database
Notice that in the previous step when you typed `juju run-action data-integrator/leader get-credentials --wait` the command not only outputted the username, password, and database, but also outputted the URI. This means you do not have to generate the URI yourself. To connect to this URI first ssh into `mongodb/0`:
```shell
juju ssh mongodb/0
```
Then access `mongosh` with the URI that you copied above:

```shell
mongosh "<uri copied from juju run-action data-integrator/leader get-credentials --wait>"
```
*Note: be sure you wrap the URI in `"` with no trailing whitespace*.

You will now be in the mongo shell as the user created for this relation. When you relate two applications Charmed MongoDB automatically sets up a user and database for you. Enter `db.getName()` into the MongoDB shell, this will output:
```shell
test-database
```
This is the name of the database we specified when we first deployed the `data-integrator` charm. To create a collection in the "test-database" and then show the collection enter:
```shell
db.createCollection("test-collection")
show collections
```
Now insert a document into this database:
```shell
db.test_collection.insertOne(
  {
    First_Name: "Jammy",
    Last_Name: "Jellyfish",
  })
```
You can verify this document was inserted by running:
```shell
db.test_collection.find()
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

### Remove the user
To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:
```shell
juju remove-relation mongodb data-integrator
```

Now try again to connect to the same URI you just used in [Access the related database](#access-the-related-database):
```shell
juju ssh mongodb/0
mongosh "<uri copied from juju run-action data-integrator/leader get-credentials --wait>"
```
*Note: be sure you wrap the URI in `"` with no trailing whitespace*.

This will output an error message:
```
Current Mongosh Log ID: 638f5ffbdbd9ec94c2e58456
Connecting to:    mongodb://<credentials>@10.23.62.38,10.23.62.219/mongodb?replicaSet=mongodb&authSource=admin&appName=mongosh+1.6.1
MongoServerError: Authentication failed.
```
As this user no longer exists. This is expected as `juju remove-relation mongodb data-integrator` also removes the user. 

Now exit the MongoDB shell by typing:
```shell
exit
```
Now you should be back in the host of Charmed MongoDB (`mongodb/0`). To exit this host type:
```shell
exit
```
You should now be shell you started in where you can interact with Juju and LXD.

If you wanted to recreate this user all you would need to do is relate the the two applications again:
```shell
juju relate data-integrator mongodb
```
Re-relating generates a new password for this user, and therefore a new URI you can see the new URI with:
```shell
juju run-action data-integrator/leader get-credentials --wait
```
Save the result listed with `uris:`.

You can connect to the database with this new URI:
```shell
juju ssh mongodb/0
mongosh "<uri copied from juju run-action data-integrator/leader get-credentials --wait>"
```
*Note: be sure you wrap the URI in `"` with no trailing whitespace*.

From there if you enter `db.test_collection.find()` you will see all of your original documents are still present in the database.