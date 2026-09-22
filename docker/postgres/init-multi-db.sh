#!/usr/bin/env bash
# Runs once, on first container init (postgres entrypoint convention: anything
# in /docker-entrypoint-initdb.d runs only against an empty data directory).
# Creates the two extra logical databases (airflow_db, mlflow_db) alongside
# the default POSTGRES_DB (weather_db) that postgres itself already created,
# all owned by the same POSTGRES_USER so no extra credentials are needed.
set -euo pipefail

for db in "${POSTGRES_AIRFLOW_DB:-airflow_db}" "${POSTGRES_MLFLOW_DB:-mlflow_db}"; do
  echo "Creating database '${db}' (if not exists)..."
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    SELECT 'CREATE DATABASE "${db}" OWNER "${POSTGRES_USER}"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${db}')\gexec
EOSQL
done
