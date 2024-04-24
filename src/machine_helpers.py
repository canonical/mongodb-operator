"""Machine Charm specific functions for operating MongoDB."""

# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import logging

import jinja2
from charms.mongodb.v0.mongodb import MongoDBConfiguration
from charms.mongodb.v1.helpers import (
    LOG_DIR,
    MONGODB_COMMON_DIR,
    add_args_to_env,
    get_mongod_args,
    get_mongos_args,
)

from config import Config

logger = logging.getLogger(__name__)

DB_PROCESS = "/usr/bin/mongod"
ROOT_USER_GID = 0
MONGO_USER = "snap_daemon"


def update_mongod_service(
    auth: bool, machine_ip: str, config: MongoDBConfiguration, role: str = "replication"
) -> None:
    """Updates the mongod service file with the new options for starting."""
    # write our arguments and write them to /etc/environment - the environment variable here is
    # read in in the charmed-mongob.mongod.service file.
    mongod_start_args = get_mongod_args(config, auth, role=role, snap_install=True)
    add_args_to_env("MONGOD_ARGS", mongod_start_args)

    if role == Config.Role.CONFIG_SERVER:
        mongos_start_args = get_mongos_args(config, snap_install=True)
        add_args_to_env("MONGOS_ARGS", mongos_start_args)


def setup_logrotate_and_cron() -> None:
    """Create and write the logrotate config file.

    Logs will be rotated if they are bigger than 100M,
    which is specified in 'templates/logrotate.j2'.

    Cron job to for starting log rotation will be run every minute
    """
    logger.debug("Creating logrotate config file")

    with open("templates/logrotate.j2", "r") as file:
        template = jinja2.Template(file.read())

    rendered = template.render(
        logs_directory=f"{MONGODB_COMMON_DIR}/{LOG_DIR}",
        mongo_user=MONGO_USER,
    )

    with open("/etc/logrotate.d/mongodb", "w") as file:
        file.write(rendered)

    cron = "* * * * * root logrotate -f /etc/logrotate.d/mongodb\n"
    with open("/etc/cron.d/mongodb", "w") as file:
        file.write(cron)
