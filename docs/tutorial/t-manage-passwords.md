# Manage Passwords

This is part of the [Charmed MongoDB Tutorial](https://discourse.charmhub.io/t/charmed-mongodb-tutorial/8061). Please refer to this page for more information and the overview of the content.

## Passwords

When we accessed MongoDB earlier in this tutorial, we needed to include a password in the URI. Passwords help to secure our database and are essential for security. Over time it is a good practice to change the password frequently. Here we will go through setting and changing the password for the admin user.

### Retrieve the admin password
As previously mentioned, the admin password can be retrieved by running the `get-password` action on the Charmed MongoDB application:
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
The admin password is under the result: `admin-password`.


### Rotate the admin password
You can change the admin password to a new random password by entering:
```shell
juju run-action mongodb/leader set-password --wait
```
Running the command should output:
```yaml
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

*Note when you change the admin password you will also need to update the admin password the in MongoDB URI; as the old password will no longer be valid.* Update the DB password used in the URI and update the URI:
```shell
export DB_PASSWORD=$(juju run-action mongodb/leader get-password --wait | grep admin-password|  awk '{print $2}')
export URI=mongodb://$DB_USERNAME:$DB_PASSWORD@$HOST_IP/$DB_NAME?replicaSet=$REPL_SET_NAME
```

### Set the admin password
You can change the admin password to a specific password by entering:
```shell
juju run-action mongodb/leader set-password password=<password> --wait
```
Running the command should output:
```yaml
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

*Note that when you change the admin password you will also need to update the admin password in the MongoDB URI, as the old password will no longer be valid.* To update the DB password used in the URI:
```shell
export DB_PASSWORD=$(juju run-action mongodb/leader get-password --wait | grep admin-password|  awk '{print $2}')
export URI=mongodb://$DB_USERNAME:$DB_PASSWORD@$HOST_IP/$DB_NAME?replicaSet=$REPL_SET_NAME
```