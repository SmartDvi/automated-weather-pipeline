"""Every 15 minutes: freshness/range/completeness checks for every active
location, logged to ops.data_quality_checks and alerted (via the stub in
weatherml/quality/alerting.py) on any critical failure. A single task — the
checks themselves loop over locations — since a partial failure here should
still record every location's results, not abort early.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

WEATHERML_PYTHON = "/opt/weatherml-venv/bin/python"

default_args = {
    "owner": "weatherml",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


@dag(
    dag_id="data_quality_monitoring",
    description="Freshness/range/completeness checks across all active locations.",
    schedule="*/15 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["data-quality", "weather"],
)
def data_quality_monitoring():
    @task.bash
    def quality_check() -> str:
        run_id = get_current_context()["run_id"]
        return f"{WEATHERML_PYTHON} -m weatherml.cli quality-check --dag-run-id {run_id}"

    quality_check()


data_quality_monitoring()
