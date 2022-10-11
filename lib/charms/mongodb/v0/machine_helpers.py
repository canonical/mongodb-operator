"""Machine Charm specific functions for operating MongoDB."""
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
import pwd
from pathlib import Path

from charms.mongodb.v0.helpers import (
    KEY_FILE,
    TLS_EXT_CA_FILE,
    TLS_EXT_PEM_FILE,
    TLS_INT_CA_FILE,
    TLS_INT_PEM_FILE,
)
from charms.mongodb.v0.mongodb import MongoDBConfiguration
from charms.operator_libs_linux.v1 import systemd

# The unique Charmhub library identifier, never change it
LIBID = "0ef38cc7c773446b8331a71a234f3c5f"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


logger = logging.getLogger(__name__)

# systemd gives files in /etc/systemd/system/ precedence over those in /lib/systemd/system/ hence
# our changed file in /etc will be read while maintaining the original one in /lib.
MONGOD_SERVICE_UPSTREAM_PATH = "/lib/systemd/system/mongod.service"
MONGOD_SERVICE_DEFAULT_PATH = "/etc/systemd/system/mongod.service"

# restart options specify that systemd should attempt to restart the service on failure.
RESTART_OPTIONS = ["Restart=always\n", "RestartSec=5s\n"]
# limits ensure that the process will not continuously retry to restart if it continuously fails to
# restart.
RESTARTING_LIMITS = ["StartLimitIntervalSec=500\n", "StartLimitBurst=5\n"]

MONGO_USER = "mongodb"
MONGO_DATA_DIR = "/data/db"


def auth_enabled() -> bool:
    """Checks if mongod service is has auth enabled."""
    # if there are no service files then auth is not enabled
    if not os.path.exists(MONGOD_SERVICE_UPSTREAM_PATH) and not os.path.exists(
        MONGOD_SERVICE_DEFAULT_PATH
    ):
        return False

    # The default file has previority over the upstream, but when the default file doesn't exist
    # then the upstream configurations are used.
    if not os.path.exists(MONGOD_SERVICE_DEFAULT_PATH):
        return start_with_auth(MONGOD_SERVICE_UPSTREAM_PATH)

    return start_with_auth(MONGOD_SERVICE_DEFAULT_PATH)


def start_with_auth(path):
    """Returns true is a mongod service file has the auth configuration."""
    with open(path, "r") as mongodb_service_file:
        mongodb_service = mongodb_service_file.readlines()

    for _, line in enumerate(mongodb_service):
        # ExecStart contains the line with the arguments to start mongod service.
        if "ExecStart" in line and "--auth" in line:
            return True

    return False


def stop_mongod_service() -> None:
    """Stop the mongod service if running."""
    if not systemd.service_running("mongod.service"):
        return

    logger.debug("stopping mongod.service")
    try:
        systemd.service_stop("mongod.service")
    except systemd.SystemdError as e:
        logger.error("failed to stop mongod.service, error: %s", str(e))
        raise


def start_mongod_service() -> None:
    """Starts the mongod service if stopped."""
    if systemd.service_running("mongod.service"):
        return

    logger.debug("starting mongod.service")
    try:
        systemd.service_start("mongod.service")
    except systemd.SystemdError as e:
        logger.error("failed to enable mongod.service, error: %s", str(e))
        raise


def update_mongod_service(auth: bool, machine_ip: str, config: MongoDBConfiguration) -> None:
    """Updates the mongod service file with the new options for starting."""
    with open(MONGOD_SERVICE_UPSTREAM_PATH, "r") as mongodb_service_file:
        mongodb_service = mongodb_service_file.readlines()

    # replace start command with our parameterized one
    mongod_start_args = generate_service_args(auth, machine_ip, config)
    for index, line in enumerate(mongodb_service):
        if "ExecStart" in line:
            mongodb_service[index] = mongod_start_args

    # self healing is implemented via systemd
    add_self_healing(mongodb_service)

    # systemd gives files in /etc/systemd/system/ precedence over those in /lib/systemd/system/
    # hence our changed file in /etc will be read while maintaining the original one in /lib.
    with open(MONGOD_SERVICE_DEFAULT_PATH, "w") as service_file:
        service_file.writelines(mongodb_service)

    # mongod requires permissions to /data/db
    mongodb_user = pwd.getpwnam(MONGO_USER)
    os.chown(MONGO_DATA_DIR, mongodb_user.pw_uid, mongodb_user.pw_gid)

    # changes to service files are only applied after reloading
    systemd.daemon_reload()


def add_self_healing(service_lines):
    """Updates the service file to auto-restart the DB service on service failure.

    Options for restarting allow for auto-restart on crashed services, i.e. DB killed, DB frozen,
    DB terminated.
    """
    for index, line in enumerate(service_lines):
        if "[Unit]" in line:
            service_lines.insert(index + 1, RESTARTING_LIMITS[0])
            service_lines.insert(index + 1, RESTARTING_LIMITS[1])

        if "[Service]" in line:
            service_lines.insert(index + 1, RESTART_OPTIONS[0])
            service_lines.insert(index + 1, RESTART_OPTIONS[1])


def generate_service_args(auth: bool, machine_ip: str, config: MongoDBConfiguration) -> str:
    """Construct the mongod startup commandline args for systemd.

    Note that commandline arguments take priority over any user set config file options. User
    options will be configured in the config file. MongoDB handles this merge of these two
    options.
    """
    mongod_start_args = [
        "ExecStart=/usr/bin/mongod",
        # bind to localhost and external interfaces
        "--bind_ip_all",
        # part of replicaset
        f"--replSet={config.replset}",
    ]

    if auth:
        mongod_start_args.extend(["--auth"])

        if config.tls_external:
            mongod_start_args.extend(
                [
                    f"--tlsCAFile={TLS_EXT_CA_FILE}",
                    f"--tlsCertificateKeyFile={TLS_EXT_PEM_FILE}",
                    # allow non-TLS connections
                    "--tlsMode=preferTLS",
                ]
            )

        # internal TLS can be enabled only if external is enabled
        if config.tls_internal and config.tls_external:
            mongod_start_args.extend(
                [
                    "--clusterAuthMode=x509",
                    "--tlsAllowInvalidCertificates",
                    f"--tlsClusterCAFile={TLS_INT_CA_FILE}",
                    f"--tlsClusterFile={TLS_INT_PEM_FILE}",
                ]
            )
        else:
            # keyFile used for authentication replica set peers if no internal tls configured.
            mongod_start_args.extend(
                [
                    "--clusterAuthMode=keyFile",
                    f"--keyFile={KEY_FILE}",
                ]
            )

    mongod_start_args.append("\n")
    mongod_start_args = " ".join(mongod_start_args)

    return mongod_start_args


def push_file_to_unit(parent_dir, file_name, file_contents) -> None:
    """K8s charms can push files to their containers easily, this is the vm charm workaround."""
    Path(parent_dir).mkdir(parents=True, exist_ok=True)
    with open(file_name, "w") as write_file:
        write_file.write(file_contents)

    os.chmod(file_name, 0o400)
    mongodb_user = pwd.getpwnam(MONGO_USER)
    os.chown(file_name, mongodb_user.pw_uid, mongodb_user.pw_gid)


def restart_mongod_service(auth: bool, machine_ip: str, config: MongoDBConfiguration):
    """Restarts the mongod service with its associated configuration."""
    stop_mongod_service()
    update_mongod_service(auth, machine_ip, config)
    start_mongod_service()


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""
