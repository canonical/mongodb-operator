# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This file is meant to run in the background continuously writing entries to MongoDB."""
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import sys


def continous_writes(connection_string: str, starting_number: int):
    client = MongoClient(connection_string)
    db = client["new-db"]
    test_collection = db["test_collection"]
    write_value = starting_number
    while True:
        try:
            test_collection.insert_one({"number": write_value})
            # this insures that no numbers are skipped. This can be moved and analysis can be done
            # on all failed writes.
            write_value += 1
        except PyMongoError:
            # ignore all errors related to pymongo
            continue


def main():
    connection_string = sys.argv[1]
    starting_number = int(sys.argv[2])
    continous_writes(connection_string, starting_number)


if __name__ == "__main__":
    main()
