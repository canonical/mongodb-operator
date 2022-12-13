# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from subprocess import PIPE, check_output
from typing import List, Optional

import ops
import yaml
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, ConnectionFailure, OperationFailure
from pytest_operator.plugin import OpsTest
from tenacity import (
    RetryError,
    Retrying,
    retry,
    retry_if_result,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    wait_fixed,
)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
PORT = 27017
APP_NAME = METADATA["name"]
DB_PROCESS = "/usr/bin/mongod"
MONGODB_LOG_PATH = "/data/db/mongodb.log"
MONGOD_SERVICE_DEFAULT_PATH = "/etc/systemd/system/mongod.service"
TMP_SERVICE_PATH = "tests/integration/ha_tests/tmp.service"
LOGGING_OPTIONS = "--logpath=/data/db/mongodb.log --logappend"


class ProcessError(Exception):
    """Raised when a process fails."""


class ProcessRunningError(Exception):
    """Raised when a process is running when it is not expected to be."""


def replica_set_client(replica_ips: List[str], password: str, app=APP_NAME) -> MongoClient:
    """Generates the replica set URI for multiple IP addresses.

    Args:
        replica_ips: list of ips hosting the replica set.
        password: password of database.
        app: name of application which hosts the cluster.
    """
    hosts = ["{}:{}".format(replica_ip, PORT) for replica_ip in replica_ips]
    hosts = ",".join(hosts)

    replica_set_uri = f"mongodb://admin:" f"{password}@" f"{hosts}/admin?replicaSet={app}"
    return MongoClient(replica_set_uri)


async def fetch_replica_set_members(replica_ips: List[str], ops_test: OpsTest):
    """Fetches the IPs listed as replica set members in the MongoDB replica set configuration.

    Args:
        replica_ips: list of ips hosting the replica set.
        ops_test: reference to deployment.
        app: name of application which has the cluster.
    """
    # connect to replica set uri
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    client = replica_set_client(replica_ips, password, app)

    # get ips from MongoDB replica set configuration
    rs_config = client.admin.command("replSetGetConfig")
    member_ips = []
    for member in rs_config["config"]["members"]:
        # get member ip without ":PORT"
        member_ips.append(member["host"].split(":")[0])

    client.close()

    return member_ips


def unit_uri(ip_address: str, password, app=APP_NAME) -> str:
    """Generates URI that is used by MongoDB to connect to a single replica.

    Args:
        ip_address: ip address of replica/unit
        password: password of database.
        app: name of application which has the cluster.
    """
    return f"mongodb://admin:" f"{password}@" f"{ip_address}:{PORT}/admin?replicaSet={app}"


async def get_password(ops_test: OpsTest, app, down_unit=None) -> str:
    """Use the charm action to retrieve the password from provided unit.

    Returns:
        String with the password stored on the peer relation databag.
    """
    # some tests disable the network for units, so find a unit that is available
    for unit in ops_test.model.applications[app].units:
        if not unit.name == down_unit:
            unit_id = unit.name.split("/")[1]
            break

    action = await ops_test.model.units.get(f"{app}/{unit_id}").run_action("get-password")
    action = await action.wait()
    return action.results["admin-password"]


async def fetch_primary(
    replica_set_hosts: List[str], ops_test: OpsTest, down_unit=None, app=None
) -> str:
    """Returns IP address of current replica set primary."""
    # connect to MongoDB client
    app = app or await app_name(ops_test)

    password = await get_password(ops_test, app, down_unit)
    client = replica_set_client(replica_set_hosts, password, app)

    # grab the replica set status
    try:
        status = client.admin.command("replSetGetStatus")
    except (ConnectionFailure, ConfigurationError, OperationFailure):
        return None
    finally:
        client.close()

    primary = None
    # loop through all members in the replica set
    for member in status["members"]:
        # check replica's current state
        if member["stateStr"] == "PRIMARY":
            # get member ip without ":PORT"
            primary = member["name"].split(":")[0]

    return primary


async def count_primaries(ops_test: OpsTest) -> int:
    """Returns the number of primaries in a replica set."""
    # connect to MongoDB client
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    replica_set_hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    client = replica_set_client(replica_set_hosts, password, app)

    # grab the replica set status
    try:
        status = client.admin.command("replSetGetStatus")
    except (ConnectionFailure, ConfigurationError, OperationFailure):
        return None
    finally:
        client.close()

    primaries = 0
    # loop through all members in the replica set
    for member in status["members"]:
        # check replica's current state
        if member["stateStr"] == "PRIMARY":
            primaries += 1

    return primaries


@retry(
    retry=retry_if_result(lambda x: x is None),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
)
async def replica_set_primary(
    replica_set_hosts: List[str],
    ops_test: OpsTest,
    down_unit=None,
    app=None,
) -> Optional[ops.model.Unit]:
    """Returns the primary of the replica set.

    Retrying 5 times to give the replica set time to elect a new primary, also checks against the
    valid_ips to verify that the primary is not outdated.
    """
    app = app or await app_name(ops_test)
    primary_ip = await fetch_primary(replica_set_hosts, ops_test, down_unit, app)
    # return None if primary is no longer in the replica set
    if primary_ip is not None and primary_ip not in replica_set_hosts:
        return None

    for unit in ops_test.model.applications[app].units:
        if unit.public_address == str(primary_ip):
            return unit


async def retrieve_entries(ops_test, app, db_name, collection_name, query_field):
    """Retries entries from a specified collection within a specified database."""
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    password = await get_password(ops_test, app)
    client = replica_set_client(ip_addresses, password, app)

    db = client[db_name]
    test_collection = db[collection_name]

    # read all entries from original cluster
    cursor = test_collection.find({})
    cluster_entries = set()
    for document in cursor:
        cluster_entries.add(document[query_field])

    client.close()
    return cluster_entries


async def find_unit(ops_test: OpsTest, leader: bool) -> ops.model.Unit:
    """Helper function identifies the a unit, based on need for leader or non-leader."""
    ret_unit = None
    app = await app_name(ops_test)
    for unit in ops_test.model.applications[app].units:
        if await unit.is_leader_from_status() == leader:
            ret_unit = unit

    return ret_unit


async def app_name(ops_test: OpsTest) -> str:
    """Returns the name of the cluster running MongoDB.

    This is important since not all deployments of the MongoDB charm have the application name
    "mongodb".

    Note: if multiple clusters are running MongoDB this will return the one first found.
    """
    status = await ops_test.model.get_status()
    for app in ops_test.model.applications:
        # note that format of the charm field is not exactly "mongodb" but instead takes the form
        # of `local:focal/mongodb-6`
        if "mongodb" in status["applications"][app]["charm"]:
            return app

    return None


async def clear_db_writes(ops_test: OpsTest) -> bool:
    """Stop the DB process and remove any writes to the test collection."""
    await stop_continous_writes(ops_test)

    # remove collection from database
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    client = MongoClient(connection_string)
    db = client["new-db"]

    # collection for continuous writes
    test_collection = db["test_collection"]
    test_collection.drop()

    # collection for replication tests
    test_collection = db["test_ubuntu_collection"]
    test_collection.drop()

    client.close()


async def start_continous_writes(ops_test: OpsTest, starting_number: int) -> None:
    """Starts continuous writes to MongoDB with available replicas.

    In the future this should be put in a dummy charm.
    """
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    # run continuous writes in the background.
    subprocess.Popen(
        [
            "python3",
            "tests/integration/ha_tests/continuous_writes.py",
            connection_string,
            str(starting_number),
        ]
    )


async def stop_continous_writes(ops_test: OpsTest, down_unit=None) -> int:
    """Stops continuous writes to MongoDB and returns the last written value.

    In the future this should be put in a dummy charm.
    """
    # stop the process
    proc = subprocess.Popen(["pkill", "-9", "-f", "continuous_writes.py"])

    # wait for process to be killed
    proc.communicate()

    app = await app_name(ops_test)
    password = await get_password(ops_test, app, down_unit)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]

    # last written value should be the highest number in the database.
    last_written_value = test_collection.find_one(sort=[("number", -1)])
    client.close()
    return last_written_value


async def count_writes(ops_test: OpsTest, down_unit=None) -> int:
    """New versions of pymongo no longer support the count operation, instead find is used."""
    app = await app_name(ops_test)
    password = await get_password(ops_test, app, down_unit)
    hosts = [unit.public_address for unit in ops_test.model.applications[app].units]
    hosts = ",".join(hosts)
    connection_string = f"mongodb://admin:{password}@{hosts}/admin?replicaSet={app}"

    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]
    count = test_collection.count_documents({})
    client.close()
    return count


async def secondary_up_to_date(ops_test: OpsTest, unit_ip, expected_writes) -> bool:
    """Checks if secondary is up to date with the cluster.

    Retries over the period of one minute to give secondary adequate time to copy over data.
    """
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    connection_string = f"mongodb://admin:{password}@{unit_ip}:{PORT}/admin?"
    client = MongoClient(connection_string, directConnection=True)

    try:
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
            with attempt:
                db = client["new-db"]
                test_collection = db["test_collection"]
                secondary_writes = test_collection.count_documents({})
                assert secondary_writes == expected_writes
    except RetryError:
        return False
    finally:
        client.close()

    return True


def storage_type(ops_test, app):
    """Retrieves type of storage associated with an application.

    Note: this function exists as a temporary solution until this issue is resolved:
    https://github.com/juju/python-libjuju/issues/694
    """
    model_name = ops_test.model.info.name
    proc = subprocess.check_output(f"juju storage --model={model_name}".split())
    proc = proc.decode("utf-8")
    for line in proc.splitlines():
        if "Storage" in line:
            continue

        if len(line) == 0:
            continue

        if "detached" in line:
            continue

        unit_name = line.split()[0]
        app_name = unit_name.split("/")[0]
        if app_name == app:
            return line.split()[3]


def storage_id(ops_test, unit_name):
    """Retrieves  storage id associated with provided unit.

    Note: this function exists as a temporary solution until this issue is resolved:
    https://github.com/juju/python-libjuju/issues/694
    """
    model_name = ops_test.model.info.name
    proc = subprocess.check_output(f"juju storage --model={model_name}".split())
    proc = proc.decode("utf-8")
    for line in proc.splitlines():
        if "Storage" in line:
            continue

        if len(line) == 0:
            continue

        if "detached" in line:
            continue

        if line.split()[0] == unit_name:
            return line.split()[1]


async def add_unit_with_storage(ops_test, app, storage):
    """Adds unit with storage.

    Note: this function exists as a temporary solution until this issue is resolved:
    https://github.com/juju/python-libjuju/issues/695
    """
    expected_units = len(ops_test.model.applications[app].units) + 1
    prev_units = [unit.name for unit in ops_test.model.applications[app].units]
    model_name = ops_test.model.info.name
    add_unit_cmd = f"add-unit {app} --model={model_name} --attach-storage={storage}".split()
    await ops_test.juju(*add_unit_cmd)
    await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=1000)
    assert (
        len(ops_test.model.applications[app].units) == expected_units
    ), "New unit not added to model"

    # verify storage attached
    curr_units = [unit.name for unit in ops_test.model.applications[app].units]
    new_unit = list(set(curr_units) - set(prev_units))[0]
    assert storage_id(ops_test, new_unit) == storage, "unit added with incorrect storage"

    # return a reference to newly added unit
    for unit in ops_test.model.applications[app].units:
        if unit.name == new_unit:
            return unit


async def reused_storage(ops_test: OpsTest, unit_name, removal_time) -> bool:
    """Returns True if storage provided to mongod has been reused.

    MongoDB startup message indicates storage reuse:
        If member transitions to STARTUP2 from STARTUP then it is syncing/getting data from
        primary.
        If member transitions to STARTUP2 from REMOVED then it is re-using the storage we
        provided.
    """
    cat_cmd = f"run --unit {unit_name} -- cat {MONGODB_LOG_PATH}"
    return_code, output, _ = await ops_test.juju(*cat_cmd.split())

    if return_code != 0:
        raise ProcessError(
            f"Expected cat command {cat_cmd} to succeed instead it failed: {return_code}"
        )

    for line in output.split("\n"):
        if not len(line):
            continue

        item = json.loads(line)

        if "msg" not in item:
            continue

        re_use_time = convert_time(item["t"]["$date"])
        if '"newState": "STARTUP2", "oldState": "REMOVED"' in line and re_use_time > removal_time:
            return True

    return False


async def insert_focal_to_cluster(ops_test: OpsTest) -> None:
    """Inserts the Focal Fossa data into the MongoDB cluster via primary replica."""
    app = await app_name(ops_test)
    ip_addresses = [unit.public_address for unit in ops_test.model.applications[app].units]
    primary = (await replica_set_primary(ip_addresses, ops_test)).public_address
    password = await get_password(ops_test, app)
    client = MongoClient(unit_uri(primary, password, app), directConnection=True)
    db = client["new-db"]
    test_collection = db["test_ubuntu_collection"]
    test_collection.insert_one({"release_name": "Focal Fossa", "version": 20.04, "LTS": True})
    client.close()


async def kill_unit_process(ops_test: OpsTest, unit_name: str, kill_code: str):
    """Kills the DB process on the unit according to the provided kill code."""
    # killing the only replica can be disastrous
    app = await app_name(ops_test)
    if len(ops_test.model.applications[app].units) < 2:
        await ops_test.model.applications[app].add_unit(count=1)
        await ops_test.model.wait_for_idle(apps=[app], status="active", timeout=1000)

    kill_cmd = f"run --unit {unit_name} -- pkill --signal {kill_code} -f {DB_PROCESS}"
    return_code, _, _ = await ops_test.juju(*kill_cmd.split())

    if return_code != 0:
        raise ProcessError(
            f"Expected kill command {kill_cmd} to succeed instead it failed: {return_code}"
        )


async def mongod_ready(ops_test, unit_ip) -> bool:
    """Verifies replica is running and available."""
    app = await app_name(ops_test)
    password = await get_password(ops_test, app)
    client = MongoClient(unit_uri(unit_ip, password, app), directConnection=True)
    try:
        for attempt in Retrying(stop=stop_after_delay(60 * 5), wait=wait_fixed(3)):
            with attempt:
                # The ping command is cheap and does not require auth.
                client.admin.command("ping")
    except RetryError:
        return False
    finally:
        client.close()

    return True


async def db_step_down(ops_test: OpsTest, old_primary_unit: str, sigterm_time: int):
    # loop through all units that aren't the old primary
    app = await app_name(ops_test)
    for unit in ops_test.model.applications[app].units:
        # verify log file exists on this machine
        search_file = f"run --unit {unit.name} ls {MONGODB_LOG_PATH}"
        return_code, _, _ = await ops_test.juju(*search_file.split())
        if return_code == 2:
            continue

        # these log files can get quite large. According to the Juju team the 'run' command
        # cannot be used for more than 16MB of data so it is best to use juju ssh or juju scp.
        log_file = check_output(
            f"JUJU_MODEL={ops_test.model_full_name} juju ssh {unit.name} 'sudo cat {MONGODB_LOG_PATH}'",
            stderr=PIPE,
            shell=True,
            universal_newlines=True,
        )

        for line in log_file.splitlines():
            if not len(line):
                continue

            item = json.loads(line)

            step_down_time = convert_time(item["t"]["$date"])
            if (
                "Starting an election due to step up request" in line
                and step_down_time >= sigterm_time
            ):
                return True

    return False


async def all_db_processes_down(ops_test: OpsTest) -> bool:
    """Verifies that all units of the charm do not have the DB process running."""
    app = await app_name(ops_test)

    try:
        for attempt in Retrying(stop=stop_after_delay(60), wait=wait_fixed(3)):
            with attempt:
                for unit in ops_test.model.applications[app].units:
                    search_db_process = f"run --unit {unit.name} ps aux | grep {DB_PROCESS}"
                    _, processes, _ = await ops_test.juju(*search_db_process.split())

                    # `ps aux | grep {DB_PROCESS}` is a process on it's own and will be shown in
                    # the output of ps aux, hence it it is important that we check if there is
                    # more than one process containing the name `DB_PROCESS`
                    # splitting processes by "\n" results in one or more empty lines, hence we
                    # need to process these lines accordingly.
                    processes = [proc for proc in processes.split("\n") if len(proc) > 0]

                    if len(processes) > 1:
                        raise ProcessRunningError
    except RetryError:
        return False

    return True


async def update_restart_delay(ops_test: OpsTest, unit, delay: int):
    """Updates the restart delay in the DB service file.

    When the DB service fails it will now wait for `dalay` number of seconds.
    """
    # load the service file from the unit and update it with the new delay
    await unit.scp_from(source=MONGOD_SERVICE_DEFAULT_PATH, destination=TMP_SERVICE_PATH)
    with open(TMP_SERVICE_PATH, "r") as mongodb_service_file:
        mongodb_service = mongodb_service_file.readlines()

    for index, line in enumerate(mongodb_service):
        if "RestartSec" in line:
            mongodb_service[index] = f"RestartSec={delay}s\n"

    with open(TMP_SERVICE_PATH, "w") as service_file:
        service_file.writelines(mongodb_service)

    # upload the changed file back to the unit, we cannot scp this file directly to
    # MONGOD_SERVICE_DEFAULT_PATH since this directory has strict permissions, instead we scp it
    # elsewhere and then move it to MONGOD_SERVICE_DEFAULT_PATH.
    await unit.scp_to(source=TMP_SERVICE_PATH, destination="mongod.service")
    mv_cmd = f"run --unit {unit.name} mv /home/ubuntu/mongod.service {MONGOD_SERVICE_DEFAULT_PATH}"
    return_code, _, _ = await ops_test.juju(*mv_cmd.split())
    if return_code != 0:
        raise ProcessError(f"Command: {mv_cmd} failed on unit: {unit.name}.")

    # remove tmp file from machine
    subprocess.call(["rm", TMP_SERVICE_PATH])

    # reload the daemon for systemd otherwise changes are not saved
    reload_cmd = f"run --unit {unit.name} systemctl daemon-reload"
    return_code, _, _ = await ops_test.juju(*reload_cmd.split())
    if return_code != 0:
        raise ProcessError(f"Command: {reload_cmd} failed on unit: {unit.name}.")


async def update_service_logging(ops_test: OpsTest, unit, logging: bool):
    """Turns on/off logging in for the mongo daemon."""
    # load the service file from the unit and update it with the new delay
    await unit.scp_from(source=MONGOD_SERVICE_DEFAULT_PATH, destination=TMP_SERVICE_PATH)
    with open(TMP_SERVICE_PATH, "r") as mongodb_service_file:
        mongodb_service = mongodb_service_file.readlines()

    for index, line in enumerate(mongodb_service):
        if "ExecStart" not in line:
            continue
        line = line.replace("\n", "")

        if logging:
            if LOGGING_OPTIONS not in line:
                mongodb_service[index] = line + LOGGING_OPTIONS + "\n"
        else:
            if LOGGING_OPTIONS in line:
                mongodb_service[index] = line.replace(LOGGING_OPTIONS, "") + "\n"

    with open(TMP_SERVICE_PATH, "w") as service_file:
        service_file.writelines(mongodb_service)

    # upload the changed file back to the unit, we cannot scp this file directly to
    # MONGOD_SERVICE_DEFAULT_PATH since this directory has strict permissions, instead we scp it
    # elsewhere and then move it to MONGOD_SERVICE_DEFAULT_PATH.
    await unit.scp_to(source=TMP_SERVICE_PATH, destination="mongod.service")
    mv_cmd = f"run --unit {unit.name} mv /home/ubuntu/mongod.service {MONGOD_SERVICE_DEFAULT_PATH}"
    return_code, _, _ = await ops_test.juju(*mv_cmd.split())
    if return_code != 0:
        raise ProcessError(f"Command: {mv_cmd} failed on unit: {unit.name}.")

    # remove tmp file from machine
    subprocess.call(["rm", TMP_SERVICE_PATH])

    # reload the daemon for systemd otherwise changes are not saved
    reload_cmd = f"run --unit {unit.name} systemctl daemon-reload"
    return_code, _, _ = await ops_test.juju(*reload_cmd.split())
    if return_code != 0:
        raise ProcessError(f"Command: {reload_cmd} failed on unit: {unit.name}.")


@retry(stop=stop_after_attempt(8), wait=wait_fixed(15))
async def verify_replica_set_configuration(ops_test: OpsTest) -> None:
    """Verifies presence of primary, replica set members, and number of primaries."""
    app = await app_name(ops_test)
    # `get_unit_ip` is used instead of `.public_address` because of a bug in python-libjuju that
    # incorrectly reports the IP addresses after the network is restored this is reported as a
    # bug here: https://github.com/juju/python-libjuju/issues/738 . Once this bug is resolved use
    # of `get_unit_ip` should be replaced with `.public_address`
    ip_addresses = [
        await get_unit_ip(ops_test, unit.name) for unit in ops_test.model.applications[app].units
    ]

    # verify presence of primary
    new_primary = await replica_set_primary(ip_addresses, ops_test)
    assert new_primary.name, "primary not elected."

    # verify all units are running under the same replset
    member_ips = await fetch_replica_set_members(ip_addresses, ops_test)
    assert set(member_ips) == set(ip_addresses), "all members not running under the same replset"

    # verify there is only one primary
    assert (
        await count_primaries(ops_test) == 1
    ), "there are more than one primary in the replica set."


def convert_time(time_as_str: str) -> int:
    """Converts a string time representation to an integer time representation."""
    # parse time representation, provided in this format: 'YYYY-MM-DDTHH:MM:SS.MMM+00:00'
    d = datetime.strptime(time_as_str, "%Y-%m-%dT%H:%M:%S.%f%z")
    return time.mktime(d.timetuple())


def cut_network_from_unit(machine_name: str) -> None:
    """Cut network from a lxc container.

    Args:
        machine_name: lxc container hostname
    """
    # apply a mask (device type `none`)
    cut_network_command = f"lxc config device add {machine_name} eth0 none"
    subprocess.check_call(cut_network_command.split())


async def get_controller_machine(ops_test: OpsTest) -> str:
    """Return controller machine hostname.

    Args:
        ops_test: The ops test framework instance
    Returns:
        Controller hostname (str)
    """
    _, raw_controller, _ = await ops_test.juju("show-controller")

    controller = yaml.safe_load(raw_controller.strip())

    return [
        machine.get("instance-id")
        for machine in controller[ops_test.controller_name]["controller-machines"].values()
    ][0]


def is_machine_reachable_from(origin_machine: str, target_machine: str) -> bool:
    """Test network reachability between hosts.

    Args:
        origin_machine: hostname of the machine to test connection from
        target_machine: hostname of the machine to test connection to
    """
    try:
        subprocess.check_call(f"lxc exec {origin_machine} -- ping -c 3 {target_machine}".split())
        return True
    except subprocess.CalledProcessError:
        return False


async def unit_hostname(ops_test: OpsTest, unit_name: str) -> str:
    """Get hostname for a unit.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested

    Returns:
        The machine/container hostname
    """
    _, raw_hostname, _ = await ops_test.juju("ssh", unit_name, "hostname")
    return raw_hostname.strip()


def instance_ip(model: str, instance: str) -> str:
    """Translate juju instance name to IP.

    Args:
        model: The name of the model
        instance: The name of the instance

    Returns:
        The (str) IP address of the instance
    """
    output = subprocess.check_output(f"juju machines --model {model}".split())

    for line in output.decode("utf8").splitlines():
        if instance in line:
            return line.split()[2]


@retry(stop=stop_after_attempt(60), wait=wait_fixed(15))
def wait_network_restore(model_name: str, hostname: str, old_ip: str) -> None:
    """Wait until network is restored.

    Args:
        model_name: The name of the model
        hostname: The name of the instance
        old_ip: old registered IP address
    """
    # try to restore network by removing mask from eth0
    try:
        restore_network_command = f"lxc config device remove {hostname} eth0"
        subprocess.check_output(restore_network_command.split())
    except subprocess.CalledProcessError:
        # if the device was already removed then we  will get a `CalledProcessError` error. This
        # is OK
        pass

    # check network is successfully restored
    if instance_ip(model_name, hostname) == old_ip:
        raise Exception("Network not restored, IP address has not changed yet.")


async def get_unit_ip(ops_test: OpsTest, unit_name: str) -> str:
    """Wrapper for getting unit ip.

    Juju incorrectly reports the IP addresses after the network is restored this is reported as a
    bug here: https://github.com/juju/python-libjuju/issues/738 . Once this bug is resolved use of
    `get_unit_ip` should be replaced with `.public_address`

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to be tested

    Returns:
        The (str) ip of the unit
    """
    return instance_ip(ops_test.model.info.name, await unit_hostname(ops_test, unit_name))
