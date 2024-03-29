This is a How-To for performing a basic restore. To restore a backup that was made from the a *different* cluster, (i.e. cluster migration via restore), please reference the [Cluster Migration via Restore How-To](/t/cluster-migration-via-restore/8835):

Restoring from a backup requires that you:
- [Have a replica set with at least three-nodes deployed](/t/charmed-mongodb-tutorial-managing-units/8620)
- Access to S3 storage
- [Have configured settings for S3 storage](/t/configuring-settings-for-s3/8834) 
- [Have existing backups in your S3-storage](/t/how-to-create-and-list-backups/8788)

To view the available backups to restore you can enter the command `list-backups`: 
```shell
juju run-action mongodb/leader list-backups --wait
```

This should show your available backups 
```shell
    backups: |-
      backup-id             | backup-type  | backup-status
      ----------------------------------------------------
      YYYY-MM-DDTHH:MM:SSZ  | logical      | finished 
```

To restore a backup from that list, run the `restore` command and pass the `backup-id` to restore:
 ```shell
juju run-action mongodb/leader restore backup-id=YYYY-MM-DDTHH:MM:SSZ --wait
```

Your restore will then be in progress.