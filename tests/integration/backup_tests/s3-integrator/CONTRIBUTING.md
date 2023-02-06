# Contributing

## Overview

This document explains the processes and practices recommended for contributing enhancements to this operator.

- Generally, before developing enhancements to this charm, you should consider opening an issue explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev) or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Additionally, new code must pass the tests. Code review typically examines
    - code quality
    - test coverage
    - user experience for Juju administrators of this charm.
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.


## Developing


### Environment set up

This operator charm can be deployed locally using [Juju on a localhost LXD cloud](https://juju.is/docs/olm/lxd). If you do not already have a Juju controller bootstrapped, you can set one up by doing the following:

```
# install requirements 
sudo snap install charmcraft --classic
sudo snap install lxd
sudo snap install juju --classic

# configure lxd
sudo adduser $USER lxd
newgrp lxd
lxd init --auto
lxc network set lxdbr0 ipv6.address none

# bootstrap controller to lxd
juju clouds
juju bootstrap localhost overlord
```

Clone this repository:
```shell
git clone https://github.com/canonical/s3-integrator.git
cd s3-integrator/
```

Create and activate a virtualenv, and install the development requirements:
```shell
virtualenv -p python3 venv
source venv/bin/activate
pip install -r requirements.txt
```


## Testing

```shell
tox -e fmt                      # update your code according to linting rules
tox -e lint                     # code style
tox -e unit                     # unit tests
tox -e integration              # run all integration tests
tox                             # runs 'lint' and 'unit' environments
```


## Build Charm

Build the charm in this git repository using:

```shell
charmcraft pack
```

## Deploy Charm

```shell
# Create a model
juju add-model development

# Enable DEBUG logging
juju model-config logging-config="<root>=INFO;unit=DEBUG"

# Deploy the charm
juju deploy ./s3-integrator_ubuntu-20.04-amd64.charm
```


## Code overview

The core implementation of this charm is represented by the [S3IntegratorCharm](./src/charm.py) class. This class will handle the [core lifecycle events](https://juju.is/docs/sdk/events) associated with the charm.


## Canonical Contributor Agreement

Canonical welcomes contributions to the Charmed S3 Integrator Operator. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.