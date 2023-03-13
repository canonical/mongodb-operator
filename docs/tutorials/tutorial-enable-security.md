# Enable Security in your MongoDB deployment 

This is part of the [Charmed MongoDB Tutorial](/t/charmed-mongodb-tutorial/8061). Please refer to this page for more information and the overview of the content. 

## Transcript Layer Security (TLS)
[TLS](https://en.wikipedia.org/wiki/Transport_Layer_Security) is used to encrypt data exchanged between two applications; it secures data transmitted over the network. Typically, enabling TLS within a highly available database, and between a highly available database and client/server applications, requires domain-specific knowledge and a high level of expertise. Fortunately, the domain-specific knowledge has been encoded into Charmed MongoDB. This means enabling TLS on Charmed MongoDB is readily available and requires minimal effort on your end.

Again, relations come in handy here as TLS is enabled via relations; i.e. by relating Charmed MongoDB to the [TLS Certificates Charm](https://charmhub.io/tls-certificates-operator). The TLS Certificates Charm centralises TLS certificate management in a consistent manner and handles providing, requesting, and renewing TLS certificates.


### Configure TLS
Before enabling TLS on Charmed MongoDB we must first deploy the `TLS-certificates-operator` charm:
```shell
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
```shell
juju config tls-certificates-operator generate-self-signed-certificates="true" ca-common-name="Tutorial CA" 
```
*Note: this tutorial uses [self-signed certificates](https://en.wikipedia.org/wiki/Self-signed_certificate); self-signed certificates should not be used in a production cluster.*

### Enable TLS
After configuring the certificates `watch -c juju status --color` will show the status of `tls-certificates-operator` as active. To enable TLS on Charmed MongoDB, relate the two applications:
```shell
juju relate tls-certificates-operator mongodb
```

### Connect to MongoDB with TLS
Like before, generate and save the URI that is used to connect to MongoDB:
```
export URI=mongodb://$DB_USERNAME:$DB_PASSWORD@$HOST_IP$DB_NAME?replicaSet=$REPL_SET_NAME
echo $URI
```
Now ssh into `mongodb/0`:
```
juju ssh mongodb/0
```
After `ssh`ing into `mongodb/0`, we are now in the unit that is hosting Charmed MongoDB. Once TLS has been enabled we will need to change how we connect to MongoDB. Specifically we will need to specify the TLS CA file along with the TLS Certificate file. These are on the units hosting the Charmed MongoDB application in the folder `/etc/mongodb/`. If you enter: `ls /etc/mongodb/external*` you should see the external certificate file and the external CA file:
```shell
/etc/mongodb/external-ca.crt  /etc/mongodb/external-cert.pem
```

As before, we will connect to MongoDB via the saved MongoDB URI. Connect using the saved URI and the following TLS options:
```shell
mongosh mongodb://$DB_USERNAME:$DB_PASSWORD@$HOST_IP/$DB_NAME?replicaSet=$REPL_SET_NAME --tls --tlsCAFile /etc/mongodb/external-ca.crt --tlsCertificateKeyFile /etc/mongodb/external-cert.pem
```

Congratulations, you've now connected to MongoDB with TLS. Now exit the MongoDB shell by typing:
```shell
exit
```
Now you should be back in the host of Charmed MongoDB (`mongodb/0`). To exit this host type:
```shell
exit
```
You should now be shell you started in where you can interact with Juju and LXD.

### Disable TLS
To disable TLS unrelate the two applications:
```shell
juju remove-relation mongodb tls-certificates-operator
```