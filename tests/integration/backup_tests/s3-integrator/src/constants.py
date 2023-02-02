# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""File containing constants to be used in the charm."""

PEER = "s3-integrator-peers"
S3_OPTIONS = [
    "access-key",
    "secret-key",
    "region",
    "storage-class",
    "attributes",
    "bucket",
    "endpoint",
    "path",
    "s3-api-version",
    "s3-uri-style",
    "tls-ca-chain",
]
S3_MANDATORY_OPTIONS = [
    "access-key",
    "secret-key",
]
S3_LIST_OPTIONS = ["attributes", "tls-ca-chain"]
