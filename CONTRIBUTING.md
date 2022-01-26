# mongodb-operator


## Developing

As this is a machine charm, it can be deployed locally using [Juju on a local LXD cloud](https://juju.is/docs/olm/lxd). Once the controller is created, to deploy this workload you need to follow some preliminar steps.

Afer downloading the repository, create and activate a virtualenv, and install the development requirements:

```bash
$ virtualenv -p python3 venv
$ source venv/bin/activate
$ pip install -r requirements.txt
```

### Build

```bash
$ charmcraft pack
```

### Deploy

```bash
$ juju deploy ./mongodb_ubuntu-20.04-amd64.charm
```


## Testing

```shell
tox -e fmt           # update your code according to linting rules
tox -e lint          # code style
tox -e unit          # unit tests
tox -e integration   # integration tests
tox                  # runs 'lint' and 'unit' environments
```

## Code overview

TODO: expand on this section when spec doc is created

## Intended use case

TODO: expand on this section when spec doc is created

## Roadmap

TODO: expand on this section when spec doc is created
