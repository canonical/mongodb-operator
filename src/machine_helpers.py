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

logger = logging.getLogger(__name__)

ENV_VAR_PATH = "/etc/environment"
DB_PROCESS = "/usr/bin/mongod"
ROOT_USER_GID = 0
MONGO_USER = "snap_daemon"
MONGO_COMMON_DIR = "/var/snap/charmed-mongodb/common"
MONGO_DATA_DIR = f"{MONGO_COMMON_DIR}/db"


def update_mongod_service(auth: bool, machine_ip: str, config: MongoDBConfiguration) -> None:
    """Updates the mongod service file with the new options for starting."""
    with open(ENV_VAR_PATH, "r") as env_var_file:
        env_vars = env_var_file.readlines()

    # write our arguments and write them to /etc/environment - the environment variable here is
    # read in in the charmed-mongob.mongod.service file.
    mongod_start_args = generate_service_args(auth, machine_ip, config)
    args_added = False
    for index, line in enumerate(env_vars):
        if "MONGOD_ARGS" in line:
            args_added = True
            env_vars[index] = f"MONGOD_ARGS={mongod_start_args}"

    # if it is the first time adding these args to the file - will will need to append them to the
    # file
    if not args_added:
        env_vars.append(f"MONGOD_ARGS={mongod_start_args}")

    with open(ENV_VAR_PATH, "w") as service_file:
        service_file.writelines(env_vars)


def generate_service_args(auth: bool, machine_ip: str, config: MongoDBConfiguration) -> str:
    """Construct the mongod startup commandline args for systemd.

    Note that commandline arguments take priority over any user set config file options. User
    options will be configured in the config file. MongoDB handles this merge of these two
    options.
    """
    mongod_start_args = [
        # bind to localhost and external interfaces
        "--bind_ip_all",
        # part of replicaset
        f"--replSet={config.replset}",
        # db must be located within the snap common directory since the snap is strictly confined
        f"--dbpath={MONGO_DATA_DIR}",
    ]

    if auth:
        mongod_start_args.extend(["--auth"])

        if config.tls_external:
            mongod_start_args.extend(
                [
                    f"--tlsCAFile={MONGO_COMMON_DIR}/{TLS_EXT_CA_FILE}",
                    f"--tlsCertificateKeyFile={MONGO_COMMON_DIR}/{TLS_EXT_PEM_FILE}",
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
                    f"--tlsClusterCAFile={MONGO_COMMON_DIR}/{TLS_INT_CA_FILE}",
                    f"--tlsClusterFile={MONGO_COMMON_DIR}/{TLS_INT_PEM_FILE}",
                ]
            )
        else:
            # keyFile used for authentication replica set peers if no internal tls configured.
            mongod_start_args.extend(
                [
                    "--clusterAuthMode=keyFile",
                    f"--keyFile={MONGO_COMMON_DIR}/{KEY_FILE}",
                ]
            )

    mongod_start_args.append("\n")
    mongod_start_args = " ".join(mongod_start_args)

    return mongod_start_args


def push_file_to_unit(parent_dir, file_name, file_contents) -> None:
    """K8s charms can push files to their containers easily, this is the vm charm workaround."""
    Path(parent_dir).mkdir(parents=True, exist_ok=True)
    file_name = f"{parent_dir}/{file_name}"
    with open(file_name, "w") as write_file:
        write_file.write(file_contents)

    if "keyFile" in file_name:
        os.chmod(file_name, 0o400)
    else:
        os.chmod(file_name, 0o440)

    mongodb_user = pwd.getpwnam(MONGO_USER)
    os.chown(file_name, mongodb_user.pw_uid, ROOT_USER_GID)


class ApplicationHostNotFoundError(Exception):
    """Raised when a queried host is not in the application peers or the current host."""
