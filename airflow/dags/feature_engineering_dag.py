"""Computes engineered features for every active location, hourly.

Same subprocess-into-isolated-venv pattern as ingest_weather_dag.py — see
weatherml/cli.py's docstring for why.
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
    "retry_delay": timedelta(minutes=2),
}


@dag(
    dag_id="feature_engineering",
    description="Compute engineered features for every active location.",
    schedule="@hourly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["features", "weather"],
)
def feature_engineering():
    @task
    def get_active_location_ids() -> list[int]:
        result = subprocess.run(
            [WEATHERML_PYTHON, "-m", "weatherml.cli", "locations-list-active"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [loc["location_id"] for loc in json.loads(result.stdout)]

    @task
    def build_feature_commands(location_ids: list[int]) -> list[str]:
        # See ingest_weather_dag.py's build_ingest_commands: .expand()'s
        # mapped values come from XCom and are used verbatim, so the real
        # run_id must be embedded here rather than left as a Jinja template.
        run_id = get_current_context()["run_id"]
        return [
            f"{WEATHERML_PYTHON} -m weatherml.cli features-build "
            f"--location-id {location_id} --dag-run-id {run_id}"
            for location_id in location_ids
        ]

    BashOperator.partial(task_id="build_features").expand(
        bash_command=build_feature_commands(get_active_location_ids())
    )


feature_engineering()
