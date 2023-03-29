Creating and listing backups requires that you:
* [Have a replica set with at least three-nodes deployed](https://discourse.charmhub.io/t/charmed-mongodb-tutorial-managing-units/8620)
* Access to S3 storage
* [Have configured settings for S3 storage](https://discourse.charmhub.io/t/configuring-settings-for-s3/8834)

Once you have a three-node replicaset that has configurations set for S3 storage, check that Charmed MongoDB is `active` and `idle` with `juju status`. Once Charmed MongoDB is `active` and `idle`, you can create your first backup with the `create-backup` command:
```
juju run-action mongodb/leader create-backup --wait
```

You can list your available, failed, and in progress backups by running the `list-backups` command:
```
juju run-action mongodb/leader list-backups --wait
```