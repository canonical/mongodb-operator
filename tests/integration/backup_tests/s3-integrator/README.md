# S3-integrator
## Description

An operator charm providing an integrator for connecting to S3 provides.

## Usage

### Deploying the S3 Integrator

```bash
$ juju deploy ./s3-integrator_ubuntu-20.04-amd64.charm
```

### Adding your S3 Credentials

To deploy your S3 credentials to the application, run the following action:

```bash
$ juju run-action s3-integrator/leader sync-s3-credentials access-key=<your_key> secret-key=<your_secret_key>
```

### Configuring the Integrator

To configure the S3 integrator charm, you may provide the following configuration options:

- endpoint: the endpoint used to connect to the object storage.
- bucket: the bucket/container name delivered by the provider (the bucket name can be specified also on the requirer application).
- region: the region used to connect to the object storage.
- path: the path inside the bucket/container to store objects.
- attributes: the custom metadata (HTTP headers).
- s3-uri-style: the S3 protocol specific bucket path lookup type.
- storage-class:the storage class for objects uploaded to the object storage.
- tls-ca-chain: the complete CA chain, which can be used for HTTPS validation.
- s3-api-version: the S3 protocol specific API signature.

The only mandatory fields for the integrator are access-key secret-key and bucket.

In order to set ca-chain certificate use the following command:
```bash
$ juju config s3-integrator tls-ca-chain="$(base64 -w0 your_ca_chain.pem)"
```
Attributes needs to be specified in comma-separated format. 

### Configuring the Integrator

To retrieve the S3 credentials, run the following action:

```bash
$ juju run-action s3-integrator/leader get-s3-credentials --wait
```

If the credentials are not set, the action will fail.

To retrieve the set of connection parameters, run the following command:

```bash
$ juju run-action s3-integrator/leader get-s3-connection-info --wait
```


## Relations 

Relations are supported via the `s3` interface. To create a relation:

```bash
$ juju relate s3-integrator application
```
To remove relation a relation:
```bash
$ juju remove-relation s3-integrator application
```

## Security
Security issues in the Charmed S3 Integrator Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.


## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/s3-integrator/blob/main/CONTRIBUTING.md) for developer guidance.

