"""Ingests current conditions for every active location every 5 minutes.

Runs entirely via subprocess calls into /opt/weatherml-venv (see
weatherml/cli.py's module docstring for why: Airflow's own environment never
imports weatherml, avoiding a real SQLAlchemy-version conflict between
Airflow 2.x and our 2.0-style ORM). Dynamic task mapping gives each location
its own retryable, independently-observable task instance, so one city's
transient failure doesn't block the other four.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.operators.bash import BashOperator
from airflow.operators.python import get_current_context

WEATHERML_PYTHON = "/opt/weatherml-venv/bin/python"

default_args = {
    "owner": "weatherml",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
}


@dag(
    dag_id="ingest_weather",
    description="Poll weatherstack for every active location and upsert observations.",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=4),
    default_args=default_args,
    tags=["ingestion", "weather"],
)
def ingest_weather():
    @task
    def get_active_location_ids() -> list[int]:
        result = subprocess.run(
            [WEATHERML_PYTHON, "-m", "weatherml.cli", "locations-list-active"],
            capture_output=True,
            text=True,
            check=True,
        )
        locations = json.loads(result.stdout)
        return [loc["location_id"] for loc in locations]

    @task
    def build_ingest_commands(location_ids: list[int]) -> list[str]:
        # Dynamically-mapped bash_command values (via .expand()) come from
        # XCom and are used verbatim — Airflow does NOT apply Jinja
        # templating to them the way it does for a statically-defined
        # operator's bash_command. So the real run_id is embedded directly
        # here (via task context) rather than left as a "{{ run_id }}"
        # template string, which would otherwise be passed to bash literally.
        run_id = get_current_context()["run_id"]
        return [
            f"{WEATHERML_PYTHON} -m weatherml.cli ingest "
            f"--location-id {location_id} --dag-run-id {run_id}"
            for location_id in location_ids
        ]

    BashOperator.partial(task_id="ingest_location").expand(
        bash_command=build_ingest_commands(get_active_location_ids())
    )


ingest_weather()
