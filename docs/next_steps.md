# Next steps / explicitly out of scope for this version

Cut deliberately to keep the initial build shippable and reviewable. None of these are
architecturally blocked — each has an obvious integration point already in the codebase.

## Infrastructure

- **Kubernetes.** Current target is a single-host Docker Compose deployment. Moving to k8s means
  splitting each Compose service into a Deployment + Service, moving `.env` into Secrets/
  ConfigMaps, and replacing the LocalExecutor with KubernetesExecutor or CeleryExecutor for
  Airflow.
- **S3/MinIO artifact storage for MLflow.** `mlflow-server` currently uses a local Docker volume
  (`mlflow_artifacts`) via `--serve-artifacts` (the tracking server proxies all artifact I/O, so
  clients never need direct filesystem access — swapping the backend is a tracking-server-only
  change). MLflow's own docs recommend S3-compatible storage for real production use; swap
  `--artifacts-destination` to an `s3://` URI and add `AWS_*`/MinIO credentials.
- **Multi-cloud / multi-region deployment.** Not addressed at all; this is a single-host design.

## Observability

- **Prometheus/Grafana.** The API exposes `/metrics` in Prometheus format
  (`prometheus-fastapi-instrumentator`) but nothing scrapes or visualizes it yet. Add a
  `prometheus` + `grafana` service to `docker-compose.yaml` and a scrape config pointing at `api`.
- **Real alerting (Slack/PagerDuty/email).** `weatherml/quality/alerting.py::notify()` is a
  logging-only stub; every data-quality call site already funnels through it, so wiring a real
  channel is a one-function change. Same story for ingestion failures — currently only visible
  via Airflow's own retry/failure UI and `ops.pipeline_runs`.

## Security

- **API authentication.** `/predict` and the other endpoints are unauthenticated. Add an API key
  header check or OAuth2 depending on who's meant to call this.
- **Secrets management.** Currently plain `.env` files. A real deployment should use a secrets
  manager (Vault, AWS Secrets Manager, etc.) rather than env files on disk.

## Data / ML

- **Prediction reconciliation job.** `ops.model_predictions.actual_temp_c` stays NULL until
  manually backfilled (see runbook.md) — a scheduled job joining predictions against later real
  observations would enable automated accuracy-over-time / drift monitoring, which is the natural
  next step once there's enough production traffic to make it meaningful.
- **`storm_indicator` / `aqi_risk_level` as model inputs.** Currently computed and stored but
  deliberately excluded from `FEATURE_COLUMNS` (see `weatherml/ml/dataset.py`) since encoding a
  boolean + categorical alongside the numeric features is a real modeling decision, not a
  correctness requirement for a first working model.
- **Severe-weather / health-risk classification model.** The original design discussion
  considered this as a second model type; the numeric derived features it would need
  (`aqi_composite_risk_score`, `storm_indicator`, heat index) already exist in
  `features.weather_features` — only the label definition and training/serving wiring are missing.
- **More locations / configurable via API.** `core.locations` supports it structurally (just add
  rows), but there's no admin endpoint to add/deactivate a location without direct DB access.

## Orchestration

- **Airflow 3.x migration.** This project intentionally targets Airflow 2.10 LTS for
  implementation reliability (very well-documented Compose topology) and because `weatherml`'s
  code has zero coupling to Airflow's own Python environment (see README's "Why Airflow's own
  environment never imports this project's code") — the DAG files use the stable TaskFlow
  (`@dag`/`@task`) API, which carries over conceptually. Upgrading later should mostly be a
  Dockerfile base-image bump plus verifying the DAG files against 3.x's dynamic task mapping
  semantics.
