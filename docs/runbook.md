# Runbook

## Checking pipeline health

```sql
-- Recent DAG task outcomes
SELECT dag_id, task_id, status, started_at, finished_at, error_message
FROM ops.pipeline_runs
ORDER BY started_at DESC
LIMIT 20;

-- Failing data quality checks
SELECT check_name, location_id, severity, details, checked_at
FROM ops.data_quality_checks
WHERE NOT passed
ORDER BY checked_at DESC
LIMIT 20;

-- Is ingestion actually current?
SELECT l.location_key, MAX(o.observation_time) AS latest, now() - MAX(o.observation_time) AS staleness
FROM core.weather_observations o
JOIN core.locations l ON l.location_id = o.location_id
GROUP BY l.location_key;
```

Or via the Airflow UI (http://localhost:8082, or 8080 if you reverted the port mapping) — each DAG's Grid view shows per-task-instance
history and logs directly.

## Manually triggering a DAG

Airflow UI → DAGs → (dag name) → the ▶ trigger button. Or via CLI inside the scheduler container:

```bash
docker compose exec airflow-scheduler airflow dags trigger ingest_weather
docker compose exec airflow-scheduler airflow dags trigger feature_engineering
docker compose exec airflow-scheduler airflow dags trigger train_and_register_model
docker compose exec airflow-scheduler airflow dags trigger data_quality_monitoring
```

Or run the underlying CLI directly (bypassing Airflow entirely — useful for fast iteration):

```bash
docker compose exec airflow-scheduler /opt/weatherml-venv/bin/python -m weatherml.cli ingest --location-id 1
docker compose exec airflow-scheduler /opt/weatherml-venv/bin/python -m weatherml.cli train-run
```

## A location's `freshness` check is failing (critical or warning)

1. Check `ops.pipeline_runs` for the `ingest_weather` / `ingest_location_<id>` task around the
   time it started failing — `error_message` usually points straight at the cause.
2. Check `raw.weather_observations_raw` for that location's most recent rows: `is_error=true`
   rows carry `error_code`/`error_info` straight from weatherstack.
   - `error_code=101` (invalid_access_key): the API key is wrong or expired — check `.env` /
     the `WEATHERSTACK_API_KEY` secret, rotate if needed.
   - `error_code=104` (usage_limit_reached): quota exhausted — see the README's "API quota"
     section. Either upgrade the plan, widen `INGESTION_POLL_INTERVAL_MINUTES`, or wait for the
     plan's window to reset.
   - Anything else: read `error_info` — it's weatherstack's own message.
3. If `raw.weather_observations_raw` has no recent rows at all for that location, the DAG task
   itself isn't running — check the Airflow scheduler logs and confirm the DAG isn't paused.

## A model isn't promoting even though it looks better

Check `ops.pipeline_runs.extra` for the relevant `train_and_register_model` run — it records the
full `PromotionDecision.reason` string per horizon (e.g. "does not sufficiently beat production
MAE ... (required <= ...)"). This is almost always the 2% improvement-threshold guard doing its
job (see `IMPROVEMENT_THRESHOLD` in `.env`) — not a bug. If you deliberately want more aggressive
promotion, lower `IMPROVEMENT_THRESHOLD`; if a specific model version needs to be forced into
production regardless, use the MLflow UI's Model Registry page to move the alias manually.

## Rotating the weatherstack API key

1. Get a new key from the weatherstack dashboard.
2. Update `WEATHERSTACK_API_KEY` in `.env`.
3. `docker compose up -d airflow-webserver airflow-scheduler api` (recreates those containers with
   the new env var — `postgres`/`mlflow-server` don't need it and can stay running).

## Resetting the stack to a clean state (local dev only — destroys data)

```bash
docker compose down -v   # removes named volumes: pg_data, mlflow_artifacts, airflow_logs
docker compose up -d --build
# migrations run automatically via airflow-init's `airflow db migrate` for Airflow's own
# metadata; the app schema needs `alembic upgrade head` run once against the fresh weather_db:
uv run alembic upgrade head
```

## Reconciling `ops.model_predictions.actual_temp_c`

Not automated in this version (see docs/next_steps.md). To backfill manually for accuracy
analysis:

```sql
UPDATE ops.model_predictions p
SET actual_temp_c = o.temperature_c
FROM core.weather_observations o
WHERE o.location_id = p.location_id
  AND o.observation_time BETWEEN
      p.predicted_at + (p.horizon_hours || ' hours')::interval - interval '10 minutes'
      AND p.predicted_at + (p.horizon_hours || ' hours')::interval + interval '10 minutes'
  AND p.actual_temp_c IS NULL;
```
