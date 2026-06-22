# Contributing

## Overview

This document explains the processes and practices recommended for contributing enhancements to this operator.

**Note:** The charm's python business logic is written in a shared library that can be found [here](https://github.com/canonical/mongo-single-kernel-library). This is where python contributions should be made. 

- Generally, before developing enhancements to this charm, you should consider opening an issue [on Single Kernel repository](https://github.com/canonical/mongo-single-kernel-library/issues) explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us on our [Matrix channel](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) or in [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Additionally, new code must pass the tests. Code review typically examines
  - code quality
  - test coverage
  - user experience for Juju administrators of this charm.
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.
- Once the code has been merged on the [repository](https://github.com/canonical/mongo-single-kernel-library/) of the Mongo Single Kernel lib, wait for a new version of the [python package](https://pypi.org/project/mongo-charms-single-kernel/) to be published, and create a PR on this repository that bumps the version of the package, and on the 3 other repositories ([MongoDB k8s](https://github.com/canonical/mongodb-k8s-operator), [Mongos VM](https://github.com/canonical/mongos-operator) and [Mongos k8s](https://github.com/canonical/mongos-k8s-operator)).
- If you added some new interfaces, please don't forget to add them here.

## Testing

```shell
tox run -e format                   # update your code according to linting rules
tox run -e lint                     # code style
tox run -e terraform-lint           # lint / format / validate TF modules

tox run -e integration -- --model testing                                  # run all integration tests
tox run -e integration -- 'tests/integration/test_charm.py' --model testing # charm integration tests
...

# In general, to run any integration test:
tox run -e integration -- 'tests/integration/<path_to_test_module>.py' --model testing # runs <test_module> tests
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
juju deploy ./mongodb_ubuntu-24.04-amd64.charm
```


## Canonical Contributor Agreement

Canonical welcomes contributions to the Charmed MongoDB Operator. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.
