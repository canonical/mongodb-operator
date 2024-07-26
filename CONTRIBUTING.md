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

# Install environment dependencies
sudo apt-get install python3-pip python3-venv -y --no-install-recommends
python3 -m pip install pipx
python3 -m pipx ensurepath
          
pipx install tox
pipx install poetry
pipx inject poetry poetry-plugin-export
# TODO: Remove after https://github.com/python-poetry/poetry/pull/5980 is closed
poetry config warnings.export false

pipx install charmcraftcache
```

Clone this repository:
```shell
git clone https://github.com/canonical/mongodb-operator.git
cd mongodb-operator/
```

Create and activate a virtualenv, and install the development requirements:
```shell
virtualenv -p python3 venv
source venv/bin/activate
```


## Testing

```shell
tox run -e format                   # update your code according to linting rules
tox run -e lint                     # code style
tox run -e unit                     # unit tests

tox run -e integration --group='1' -m 'not unstable'                      # run all integration tests
tox run -e integration -- 'tests/integration/test_charm.py' --group='1'   # charm integration tests
...

# In general, to run any integration test:
tox run -e integration -- 'tests/integration/<path_to_test_module>.py' --group='1' # runs <test_module> tests
```

Testing high availability on a production cluster can be done with:
```shell
tox run -e integration -- 'tests/integration/ha_tests/test_ha.py' --group='1' --model=<model_name>
```

Note if you'd like to test storage reuse in ha-testing, your storage must not be of the type `rootfs`. `rootfs` storage is tied to the machine lifecycle and does not stick around after unit removal. `rootfs` storage is used by default with `tox run -e ha-integration`. To test ha-testing for storage reuse: 
```shell
juju add-model test
juju create-storage-pool mongodb-ebs ebs volume-type=standard # create a storage pool
juju deploy ./*charm --storage mongodb=mongodb-ebs,7G,1 # deploy 1 or more units of application with said storage pool
tox run -e integration -- 'tests/integration/ha_tests/test_ha.py' --group='1' --model=test # run tests in the model where you deployed the app 
```

## Build Charm

Build the charm in this git repository using:

```shell
tox run -e build-dev -- -v --bases-index='0'
```

## Deploy Charm

```shell
# Create a model
juju add-model development

# Enable DEBUG logging
juju model-config logging-config="<root>=INFO;unit=DEBUG"

# Deploy the charm
juju deploy ./mongodb_ubuntu-20.04-amd64.charm
```


## Code overview

The core implementation of this charm is represented by the [MongodbOperatorCharm](./src/charm.py) class. This class will handle the [core lifecycle events](https://juju.is/docs/sdk/events) associated with the charm:
- Download and installation of MongoDB, using the [operator_libs_linux](./lib/charms/operator_libs_linux/v0/) library.
- Configuration changes to `/etc/mongod.conf`
- Starting of MongoDB daemon `mongod` for the unit as a single replica

The class [MongoDB](./src/mongoserver.py) is a helper module. It provides utilities to communicate with a MongoDB database. This class is used by the core `MongodbOperatorCharm` to get information and interact with the database.


## Intended use case

TODO: expand on this section when spec doc is created


## Canonical Contributor Agreement

Canonical welcomes contributions to the Charmed MongoDB Operator. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.
