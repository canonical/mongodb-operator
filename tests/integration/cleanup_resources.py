# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
import multiprocessing
import subprocess

logger = logging.getLogger(__name__)


def destroy_model(model):
    logger.info(f"Destroying model '{model}' ")
    delete_cmd = ["juju", "destroy-model", model, "--destroy-storage", "-y"]
    subprocess.check_output(delete_cmd)


def cleanup_juju_models() -> None:
    models = _filter_tests_models("admin/test-")
    with multiprocessing.Pool() as pool:
        pool.map(destroy_model, models)


def _filter_tests_models(prefix: str):
    cmd = ["juju", "models", "--format", "json"]
    models_str = subprocess.check_output(cmd).decode("utf-8")

    models = json.loads(models_str)["models"]
    filtered_models = [model["name"] for model in models if model["name"].startswith(prefix)]

    return filtered_models


if __name__ == "__main__":
    cleanup_juju_models()
