# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This file is meant to run in the background continuously writing entries to MongoDB."""
import sys

from pymongo import MongoClient
from pymongo.errors import PyMongoError, AutoReconnect


def continous_writes(connection_string: str, starting_number: int):
    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]
    write_value = starting_number
    while True:
        try:
            test_collection.insert_one({"number": write_value})
        except AutoReconnect:
            # this means that the primary was not able to be found. An application should try to
            # reconnect and re-write the previous value. Hence, we `continue` here, without
            # incrementing `write_value` as to try to insert this value again.
            continue
        except PyMongoError:
            # we should not raise this exception but instead increment the write value and move
            # on, indicating that there was a failure writing to the database.
            pass

        write_value += 1


def main():
    connection_string = sys.argv[1]
    starting_number = int(sys.argv[2])

    continous_writes(connection_string, starting_number)


if __name__ == "__main__":
    main()
