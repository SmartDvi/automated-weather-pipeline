# WeatherML — Production Weather Ingestion, Feature Engineering & Forecasting

A self-hosted pipeline that polls [weatherstack](https://weatherstack.com/) once a day for
5 cities, engineers meteorological/health-risk features, trains short-term temperature forecasting
models tracked in MLflow, and serves predictions over a FastAPI. Orchestrated end-to-end by
Airflow, with a read-only Dash dashboard for browsing ingested data and forecasts.

## Architecture
[Screencast from 2026-09-23 02-06-43.webm](https://github.com/user-attachments/assets/6096e1d6-7a77-4632-b8fb-d18e01a61170)

weatherstack API
      │  every 5 min (Airflow: ingest_weather)
      ▼
raw.weather_observations_raw  ──►  core.weather_observations  (Postgres, idempotent upsert)
                                          │  hourly (Airflow: feature_engineering)
                                          ▼
                              features.weather_features
                                          │  daily (Airflow: train_and_register_model)
                                          ▼
                              MLflow tracking + model registry
                              (weather_temp_forecast_1h / _3h, @production alias)
                                          │
                                          ▼
                              FastAPI (/predict, /observations, /health, /metrics)
                                          │
                                          ▼
                              Dash dashboard (read-only, never calls weatherstack)

ops.pipeline_runs / ops.data_quality_checks   ◄── every 15 min (Airflow: data_quality_monitoring)
```

Six Docker Compose services: `postgres` (three logical databases: `weather_db`, `airflow_db`,
`mlflow_db`), `mlflow-server`, `airflow-webserver` + `airflow-scheduler`, `api`.

**Why Airflow's own environment never imports this project's code**: Airflow 2.x pins
SQLAlchemy `<2.0`; this project's ORM uses SQLAlchemy 2.0's `Mapped`/`mapped_column` API, and
also needs mlflow/xgboost/pandas which would fight Airflow's own dependency constraints. Instead,
`weatherml` is installed into a *separate* venv baked into the same Airflow image
(`/opt/weatherml-venv`), and every DAG task shells out to
`/opt/weatherml-venv/bin/python -m weatherml.cli <subcommand>` (see `src/weatherml/cli.py`).
Airflow's own environment stays completely vanilla — upgrading Airflow later touches nothing here.

## Quickstart

```bash
cp .env.example .env
# edit .env: set WEATHERSTACK_API_KEY, POSTGRES_PASSWORD, AIRFLOW__WEBSERVER__SECRET_KEY,
# AIRFLOW__CORE__FERNET_KEY (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

docker compose up -d --build
```

- Airflow UI: http://localhost:8082 (user/pass from `AIRFLOW_ADMIN_USER`/`AIRFLOW_ADMIN_PASSWORD`)
- MLflow UI: http://localhost:5001 (see note on port below)
- API: http://localhost:8811/docs

Wait for one 5-minute `ingest_weather` cycle, then check:

```bash
docker compose exec postgres psql -U weatherdb_user -d weather_db \
  -c "SELECT location_id, observation_time, temperature_c FROM core.weather_observations;"
```

Local dev / first run: set `USE_MOCK_CLIENT=true` in `.env` to exercise the whole pipeline with
synthetic data and zero real API calls (see "API quota" below).

## API quota — read before setting a short poll interval

5 cities × every 5 minutes = 1,440 requests/day ≈ **43,200/month**. This is almost certainly
above a weatherstack free-tier allowance. Before going live, either:

- size your weatherstack plan for `INGESTION_POLL_INTERVAL_MINUTES` × number of active locations, or
- widen `INGESTION_POLL_INTERVAL_MINUTES` in `.env`, or
- keep `USE_MOCK_CLIENT=true` for anything other than a real deployment.

weatherstack also returns **HTTP 200 with an `{"error": {...}}` body** on failures (bad key, bad
query, quota exhausted) rather than a proper error status — `weatherml/ingestion/client.py`
handles this explicitly and classifies errors as retryable (quota/rate-limit) vs. non-retryable
(bad key/query, which retrying can't fix).

## Database schema

One Postgres 16 instance, three logical databases (`weather_db` managed by Alembic;
`airflow_db`/`mlflow_db` self-migrated by their own services). `weather_db` uses four schemas:

| Schema | Purpose |
|---|---|
| `core` | `locations` (dimension, 5 seeded cities) and `weather_observations` (cleaned fact table, `UNIQUE(location_id, observation_time)` is the idempotency key) |
| `raw` | `weather_observations_raw` — append-only landing table, one row per API poll attempt (success or failure), full JSON preserved |
| `features` | `weather_features` — engineered features, no stored label (targets are joined forward from `core.weather_observations` at training time, which structurally prevents leakage) |
| `ops` | `pipeline_runs` (audit log every DAG task writes to), `data_quality_checks`, `model_predictions` (online monitoring log written by `/predict`) |

See `src/weatherml/db/models.py` for full column definitions and `migrations/versions/` for the
Alembic history.

## Feature engineering

Pure, unit-tested functions in `src/weatherml/features/functions.py`: lag/rolling temperature
stats, rate of change, pressure trend (storm precursor signal), cyclical hour/day-of-year
encoding, heat index (NWS Rothfusz regression), dew point (Magnus-Tetens), wind chill, and a
composite air-quality risk score/level. These are both model inputs and standalone
alerting-worthy signals (e.g. `storm_indicator`, `aqi_risk_level`) — the framing behind this
project's feature set is "features that answer a real question" (is this dangerous, is a storm
coming), not generic statistical transforms.

## ML: short-term temperature forecasting

Two independently-registered models, `weather_temp_forecast_1h` and `_3h` (genuinely different
tasks, independent promotion timelines). Every training run (`train_and_register_model` DAG,
daily) logs an XGBoost candidate *and* a naive persistence baseline
(`temp(t+h) = temp(t)`) side by side — a candidate that can't beat the baseline is never
promoted. A candidate is promoted to the `@production` alias only if it also beats the
*current* production model (re-evaluated on the same held-out split) by at least
`IMPROVEMENT_THRESHOLD` (default 2%), avoiding alias churn on noise. See
`src/weatherml/ml/registry.py::decide_promotion` (a pure function, fully unit-tested).

Training is skipped (not run on too little data) below `MIN_TRAINING_ROWS` — see
`src/weatherml/ml/train.py`.

## Serving API

`GET /health`, `GET /locations`, `GET /observations/{id}/latest`, `GET /observations/{id}`,
`POST /predict` (writes to `ops.model_predictions` for future accuracy tracking), `GET /metrics`
(Prometheus format). The model cache refreshes from the MLflow registry every
`MODEL_REFRESH_INTERVAL_SECONDS` (default 600s) without restarting the process, and only swaps
the in-memory model when the resolved `@production` version actually changed.

## Dashboard

A read-only Dash + Dash Mantine Components app (`src/weatherml/dashboard/`) for browsing ingested
observations and forecasts. It only calls this project's own API — never weatherstack directly —
so leaving it open, or setting a short `DASHBOARD_REFRESH_SECONDS`, never touches weatherstack
quota; only Airflow's `ingest_weather` DAG does that.

```bash
uv sync --extra dashboard
docker compose up -d postgres mlflow-server api   # or the full stack
uv run python -m weatherml.dashboard.app
```

Dashboard: http://localhost:8050 (port / refresh interval / API base URL configurable via
`DASHBOARD_PORT` / `DASHBOARD_REFRESH_SECONDS` / `DASHBOARD_API_BASE_URL` in `.env`).

Per selected location, it shows current conditions, `/predict` forecasts for both horizons, a 24h
temperature chart, and a "data insights" AG Grid table of recent observations enriched with
`heat_index_c`, `dew_point_c`, `wind_chill_c`, `pressure_trend_3h`, and `storm_risk`. These are
computed by calling the same functions in `weatherml/features/functions.py` used to build model
training features (see `src/weatherml/dashboard/insights.py`) — not a reimplementation.

## Testing

```bash
uv sync --all-extras
uv run pytest tests/unit           # pure functions, mocked HTTP — no infra needed
uv run pytest tests/integration    # real Postgres via testcontainers (needs Docker)
uv run ruff check . && uv run ruff format --check .
```

## Known ports

Host ports are shifted from the usual defaults because this machine had other local services
already bound to them — internal Docker networking (service-name DNS, unaffected default ports)
is unchanged either way:

| Service | Host port | Default | Why |
|---|---|---|---|
| `mlflow-server` | 5001 | 5000 | another local MLflow instance was already on 5000 |
| `airflow-webserver` | 8082 | 8080 | another local service was already on 8080 |
| `api` | 8811 | 8000 | another local service was already on 8000 |

Adjust the `ports:` mappings in `docker-compose.yaml` back to the defaults if your machine is
free of conflicts.

## What's deliberately out of scope for this version

See [docs/next_steps.md](docs/next_steps.md): Kubernetes, S3/MinIO artifact storage,
Prometheus/Grafana dashboards, real alerting integrations (Slack/PagerDuty — a logging stub
exists at every call site, see `weatherml/quality/alerting.py`), multi-cloud deployment, and API
authentication.

## Operations

See [docs/runbook.md](docs/runbook.md) for common operational tasks (manually triggering a DAG,
diagnosing a data-quality alert, rotating the API key, resetting the stack).
