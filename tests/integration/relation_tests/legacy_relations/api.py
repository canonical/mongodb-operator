# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Manage graylog via its API.

NOTE: This file is taken directly from the original graylog charm:
https://launchpad.net/charm-graylog and modified to include only the functions used in the
integration tests. This file should not be modified as it directly models how the graylog charm
interfaces with its API.
"""
import json
import os

import requests

# When using 'certifi' from the virtualenv, the system-wide certificates store
# is not used, so installed certificates won't be used to validate hosts.
# Adding the system CA bundle
# https://git.launchpad.net/ubuntu/+source/python-certifi/tree/debian/patches/0001-Use-Debian-provided-etc-ssl-certs-ca-certificates.cr.patch
SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
DEFAULT_BACKEND_USER_ROLE = "Reader"

# We are in a charm environment
charm = False
if os.environ.get("JUJU_UNIT_NAME"):
    from charmhelpers.core import hookenv
    from charmhelpers.core.hookenv import log

    charm = True


def get_ignore_indexer_failures_file():  # noqa: D103
    return "/usr/local/lib/nagios/plugins/ignore_indexer_failures.timestamp"


class GraylogApi:
    """Manage Graylog via its API."""

    def __init__(self, base_url, username, password, token_name="graylog-api", verify=None):
        """Initialize HTTP values."""
        self.base_url = base_url
        if not base_url.endswith("/"):
            self.base_url += "/"
        self.username = username
        self.password = password
        self.auth = (self.username, self.password)
        self.token_name = token_name
        self.token = None
        self.input_types = None
        self.req_timeout = 3
        self.req_retries = 4
        self.verify = verify

    def request(self, path, method="GET", data={}, params=None, prime_token=True):  # noqa: C901
        """Retrieve data by URL.

        To avoid recursion when self.request is used in token_get, set prime_token=False
        """
        if prime_token and not self.token:
            self.token_get()
        if path.startswith("/"):
            path = path[1:]
        url = "{}{}?pretty=true".format(self.base_url, path)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Encoding": "",
            "X-Requested-By": "Graylog Charm",
        }
        if data:
            data = json.dumps(data, indent=True)
        tries = 0
        while tries < self.req_retries:
            tries += 1
            try:
                resp = requests.api.request(
                    method,
                    url,
                    auth=self.auth,
                    data=data,
                    params=params,
                    headers=headers,
                    timeout=self.req_timeout,
                    verify=SYSTEM_CA_BUNDLE if self.verify is None else self.verify,
                )
                if resp.ok:
                    if method == "DELETE":
                        return True
                    if resp.content:
                        return resp.json()
                else:
                    msg = "API error code: {}".format(resp.status_code)
                    if charm:
                        log(msg)
                        hookenv.status_set("blocked", msg)
                    else:
                        print(msg)
            except Exception as ex:
                msg = "Error calling graylog api: {}".format(ex)
                if charm:
                    log(msg)
                else:
                    print(msg)

    def token_get(self, token_name=None, halt=False):
        """Return a token."""
        if self.token:
            return self.token
        if not token_name:
            token_name = self.token_name
        if self.password == "token":
            self.token = self.username
            self.auth = (self.token, "token")
            return self.token
        url = "users/{}/tokens".format(self.username)
        resp = self.request(url, prime_token=False)
        if not resp:
            return
        for token in resp["tokens"]:
            if token["name"] == token_name:
                self.token = token["token"]
                self.auth = (token["token"], "token")
                return self.token

        # None found, let's create a new
        url = "{}/{}".format(url, token_name)
        resp = self.request(url, method="POST", prime_token=False)
        if not halt:
            return self.token_get(token_name=token_name, halt=True)
        else:
            if charm:
                hookenv.status_set("blocked", "Cannot get API token.")
            return None  # Don't loop until we run out of memory.

    def user_get(self, username):
        """Return a user."""
        url = "users/{}".format(username)
        return self.request(url)

    def user_create(self, username, password, read_only=True):
        """Create a user."""
        user = self.user_get(username)
        if user:
            return user
        url = "users/"
        d = {
            "username": username,
            "password": password,
            "full_name": username,
            "email": "{}@local".format(username),
            "permissions": [],
        }
        self.request(url, method="POST", data=d)
        return self.user_get(username)

    def user_permissions_clear(self, username):
        """Remove permissions from a user."""
        user = self.user_get(username)
        if not user:
            return
        url = "users/{}/permissions".format(username)
        self.request(url, method="DELETE")

    def user_permissions_set(self, username, permission):
        """Add permissions to a user."""
        user = self.user_get(username)
        if not user:
            return
        url = "users/{}/permissions".format(username)
        self.request(url, method="PUT", data={"permissions": permission})
