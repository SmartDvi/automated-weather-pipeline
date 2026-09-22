"""API tests run against the same testcontainer Postgres as the other
integration tests, with ModelCache stubbed (a deterministic fake model) so
no live MLflow server is required in CI — see docs/next_steps.md for the
manually-run, @pytest.mark.slow live-MLflow smoke test.
"""

from datetime import UTC, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from weatherml.api.main import app
from weatherml.api.model_loader import LoadedModel, model_cache
from weatherml.common.audit import track_run
from weatherml.db.models import Location, WeatherObservation


class _StubModel:
    def predict(self, X: pd.DataFrame):
        return [15.5] * len(X)


@pytest.fixture(autouse=True)
def _no_real_mlflow_refresh(monkeypatch):
    # The app's lifespan calls model_cache.refresh() on startup, which would
    # otherwise try to reach a real MLflow server.
    monkeypatch.setattr(model_cache, "refresh", lambda: None)
    yield
    model_cache._models = dict.fromkeys(model_cache.horizons)


def test_health_locations_observations_and_predict(db_session):
    location = db_session.query(Location).filter_by(location_key="new_york_us").one()
    # /predict has no as_of override — it always builds features against
    # "now" internally — so the seeded observation must be recent, not an
    # arbitrary fixed date, or it falls outside the feature lookback window.
    base = datetime.now(UTC)
    with track_run(db_session, dag_id="test", task_id="test") as run:
        db_session.add(
            WeatherObservation(
                location_id=location.location_id,
                observation_time=base,
                temperature_c=12.0,
                humidity_pct=55,
                pressure_hpa=1012.0,
                wind_speed_kph=8.0,
                precip_mm=0.0,
                ingestion_run_id=run.run_id,
            )
        )
    db_session.commit()

    model_cache._models[1] = LoadedModel(
        model=_StubModel(), version="1", loaded_at=datetime.now(UTC)
    )

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["db_ok"] is True

        locations = client.get("/locations")
        assert locations.status_code == 200
        assert any(loc["location_key"] == "new_york_us" for loc in locations.json())

        latest = client.get(f"/observations/{location.location_id}/latest")
        assert latest.status_code == 200
        assert latest.json()["temperature_c"] == 12.0

        predicted = client.post(
            "/predict", json={"location_id": location.location_id, "horizon_hours": 1}
        )
        assert predicted.status_code == 200
        body = predicted.json()
        assert body["predicted_temp_c"] == 15.5
        assert body["model_version"] == "1"


def test_predict_returns_503_without_a_loaded_model(db_session):
    model_cache._models[3] = None
    location = db_session.query(Location).filter_by(location_key="tokyo_jp").one()

    with TestClient(app) as client:
        response = client.post(
            "/predict", json={"location_id": location.location_id, "horizon_hours": 3}
        )

    assert response.status_code == 503


def test_latest_observation_404_when_none_exist(db_session):
    location = db_session.query(Location).filter_by(location_key="lagos_ng").one()

    with TestClient(app) as client:
        response = client.get(f"/observations/{location.location_id}/latest")

    assert response.status_code == 404
