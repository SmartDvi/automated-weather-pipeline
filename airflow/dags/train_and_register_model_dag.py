"""Daily: trains a candidate model per forecast horizon, evaluates against
the naive persistence baseline and the current @production model on a
time-ordered held-out split, and promotes if it clears the bar (see
weatherml/ml/registry.py::decide_promotion). Single task, not per-location —
training pools data across all active locations into one model per horizon.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

WEATHERML_PYTHON = "/opt/weatherml-venv/bin/python"

default_args = {
    "owner": "weatherml",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="train_and_register_model",
    description="Train, evaluate, and maybe promote temperature forecasting models per horizon.",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    default_args=default_args,
    tags=["ml", "training", "weather"],
)
def train_and_register_model():
    @task.bash
    def train_run() -> str:
        # Embed the real run_id directly (via task context) rather than a
        # "{{ run_id }}" Jinja placeholder — see ingest_weather_dag.py's
        # build_ingest_commands for why that's not safe to assume works.
        run_id = get_current_context()["run_id"]
        return f"{WEATHERML_PYTHON} -m weatherml.cli train-run --dag-run-id {run_id}"

    train_run()


train_and_register_model()
