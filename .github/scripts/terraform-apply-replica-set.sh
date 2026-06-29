#!/usr/bin/env bash
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set -euo pipefail

# Pass the Juju model name as the first argument.
model_name="${1}"
model="$(juju show-model "${model_name}" | awk -F': ' '/model-uuid/ {print $2}')"

pushd ./terraform/product/replica_set/
terraform init
terraform apply \
  -var="mongodb={\"model_uuid\": \"${model}\"}" \
  -var="self_signed_certificates={\"model_uuid\": \"${model}\"}" \
  -var="grafana_agent={\"model_uuid\": \"${model}\"}" \
  -var="s3_integrator={\"model_uuid\": \"${model}\", \"config\": {\"bucket\": \"test\"}}" \
  -var="data_integrator={\"model_uuid\": \"${model}\"}" \
  -var="charmed_etcd={\"model_uuid\": \"${model}\"}" \
  -auto-approve
popd
