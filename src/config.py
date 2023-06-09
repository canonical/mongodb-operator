#!/usr/bin/env python3
"""Charm code for MongoDB service."""
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

class CharmConfig:
    SUBSTRATE:str = "vm"
    GPG_URL:str = "https://www.mongodb.org/static/pgp/server-5.0.asc"
    # We expect the MongoDB container to use the default ports
    MONGODB_PORT:int = 27017
    DB_INITIALIZED:str = "db_initialized"
    SERVICE_NAME:str = "mongod"

    class Snap:
        PACKAGES:list = [("charmed-mongodb", "5/edge", 82)]
        CACHE_KEY = "charmed-mongodb"

    class Relations:
        PEERS:str = "database-peers"
        APP:str = "database"
        OBSOLETTE_RELATIONS:str = "obsolete"
        REPLICA_SET_HOSTS:str = "replica_set_hosts"

    class Secrets:
        KEY_FILE:str = "keyFile"
        APP_SCOPE:str = "app"
        UNIT_SCOPE:str = "unit"

    class Events:
        USERNAME_PARAM:str = "username"
        PASSWORD_PARAM:str = "password"

    class Monitor:
        MONGODB_EXPORTER_PORT = 9216
        ENDPOINTS:list = [
                    {"path": "/metrics", "port": f"{MONGODB_EXPORTER_PORT}"},
                ]
        RULES_DIR:str = "./src/alert_rules/prometheus"
        LOGS_RULES_DIR:str = "./src/alert_rules/loki"
        LOG_SLOTS:list = ["charmed-mongodb:logs"]
        SERVICE_NAME:str = "mongodb-exporter"
        URI_KEY:str = "monitor-uri"

    class Backup:
        SERVICE_NAME:str = "pbm-agent"
        URI_KEY:str = "pbm-uri"

