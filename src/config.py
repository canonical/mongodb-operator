"""Configuration for MongoDB Charm."""

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


from typing import Literal


class Config:
    """Configuration for MongoDB Charm."""

    MONGOS_PORT = 27018
    MONGODB_PORT = 27017
    SUBSTRATE = "vm"
    ENV_VAR_PATH = "/etc/environment"
    MONGODB_SNAP_DATA_DIR = "/var/snap/charmed-mongodb/current"
    MONGOD_CONF_DIR = f"{MONGODB_SNAP_DATA_DIR}/etc/mongod"
    MONGOD_CONF_FILE_PATH = f"{MONGOD_CONF_DIR}/mongod.conf"
    SNAP_PACKAGES = [("charmed-mongodb", "6/edge", 111)]

    # Keep these alphabetically sorted
    class Actions:
        """Actions related config for MongoDB Charm."""

        PASSWORD_PARAM_NAME = "password"
        USERNAME_PARAM_NAME = "username"

    class AuditLog:
        """Audit log related configuration."""

        FORMAT = "JSON"
        DESTINATION = "file"
        FILE_NAME = "audit.log"

    class Backup:
        """Backup related config for MongoDB Charm."""

        SERVICE_NAME = "pbm-agent"
        URI_PARAM_NAME = "pbm-uri"

    class Monitoring:
        """Monitoring related config for MongoDB Charm."""

        MONGODB_EXPORTER_PORT = 9216
        METRICS_ENDPOINTS = [
            {"path": "/metrics", "port": f"{MONGODB_EXPORTER_PORT}"},
        ]
        METRICS_RULES_DIR = "./src/alert_rules/prometheus"
        LOGS_RULES_DIR = "./src/alert_rules/loki"
        LOG_SLOTS = ["charmed-mongodb:logs"]
        URI_PARAM_NAME = "monitor-uri"
        SERVICE_NAME = "mongodb-exporter"

    class TLS:
        """TLS related config for MongoDB Charm."""

        KEY_FILE_NAME = "keyFile"
        TLS_PEER_RELATION = "certificates"
        SECRET_KEY_LABEL = "key-secret"

        EXT_PEM_FILE = "external-cert.pem"
        EXT_CA_FILE = "external-ca.crt"
        INT_PEM_FILE = "internal-cert.pem"
        INT_CA_FILE = "internal-ca.crt"
        SECRET_CA_LABEL = "ca-secret"
        SECRET_CERT_LABEL = "cert-secret"
        SECRET_CSR_LABEL = "csr-secret"
        SECRET_CHAIN_LABEL = "chain-secret"

    class Relations:
        """Relations related config for MongoDB Charm."""

        NAME = "database"
        PEERS = "database-peers"
        OBSOLETE_RELATIONS_NAME = "obsolete"
        SHARDING_RELATIONS_NAME = "sharding"
        CONFIG_SERVER_RELATIONS_NAME = "config-server"
        CLUSTER_RELATIONS_NAME = "cluster"
        APP_SCOPE = "app"
        UNIT_SCOPE = "unit"
        DB_RELATIONS = [OBSOLETE_RELATIONS_NAME, NAME]
        Scopes = Literal[APP_SCOPE, UNIT_SCOPE]

    class Role:
        """Role config names for MongoDB Charm."""

        CONFIG_SERVER = "config-server"
        REPLICATION = "replication"
        SHARD = "shard"

    class Secrets:
        """Secrets related constants."""

        SECRET_LABEL = "secret"
        SECRET_CACHE_LABEL = "cache"
        SECRET_KEYFILE_NAME = "keyfile"
        SECRET_INTERNAL_LABEL = "internal-secret"
        SECRET_DELETED_LABEL = "None"
        MAX_PASSWORD_LENGTH = 4096
