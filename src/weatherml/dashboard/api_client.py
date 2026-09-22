"""HTTP client the dashboard uses to talk to the WeatherML API.

This only ever calls `weatherml`'s own FastAPI service, which reads from
Postgres. It never calls weatherstack directly — that only happens inside
Airflow's `ingest_weather` DAG, on `INGESTION_POLL_INTERVAL_MINUTES`. So
however often the dashboard refreshes, it does not consume weatherstack quota.
"""

from __future__ import annotations

import requests

from weatherml.config import get_settings

_TIMEOUT = 10


def _base_url() -> str:
    return get_settings().dashboard_api_base_url.rstrip("/")


def get_locations() -> list[dict]:
    resp = requests.get(f"{_base_url()}/locations", timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_latest_observation(location_id: int) -> dict | None:
    resp = requests.get(f"{_base_url()}/observations/{location_id}/latest", timeout=_TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def get_observation_history(location_id: int, limit: int = 288) -> list[dict]:
    resp = requests.get(
        f"{_base_url()}/observations/{location_id}",
        params={"limit": limit},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def predict(location_id: int, horizon_hours: int) -> dict | None:
    resp = requests.post(
        f"{_base_url()}/predict",
        json={"location_id": location_id, "horizon_hours": horizon_hours},
        timeout=_TIMEOUT,
    )
    if resp.status_code in (404, 503):
        return None
    resp.raise_for_status()
    return resp.json()
