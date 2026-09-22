#!/usr/bin/env bash
# --serve-artifacts makes this server proxy artifact upload/download over its
# HTTP API, so client containers (airflow, api) never need direct filesystem
# access to the artifact volume - they only need the tracking URI.
set -euo pipefail

exec mlflow server \
  --host 0.0.0.0 \
  --port 5000 \
  --backend-store-uri "${MLFLOW_BACKEND_STORE_URI}" \
  --artifacts-destination "${MLFLOW_ARTIFACT_ROOT}" \
  --serve-artifacts
