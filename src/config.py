"""Configuration for MongoDB Charm."""
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


class Config:
    """Configuration for MongoDB Charm."""

    SUBSTRATE = "vm"
    # We expect the MongoDB container to use the default ports
    MONGODB_PORT = 27017
    ENV_VAR_PATH = "/etc/environment"
    MONGODB_SNAP_DATA_DIR = "/var/snap/charmed-mongodb/current"
    MONGOD_CONF_DIR = f"{MONGODB_SNAP_DATA_DIR}/etc/mongod"
    MONGOD_CONF_FILE_PATH = f"{MONGOD_CONF_DIR}/mongod.conf"
    SNAP_PACKAGES = [("charmed-mongodb", "5/edge", 82)]

    class Actions:
        """Actions related config for MongoDB Charm."""

        PASSWORD_PARAM_NAME = "password"
        USERNAME_PARAM_NAME = "username"

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

    class Relations:
        """Relations related config for MongoDB Charm."""

        NAME = "database"
        PEERS = "database-peers"
        OBSOLETE_RELATIONS_NAME = "obsolete"
