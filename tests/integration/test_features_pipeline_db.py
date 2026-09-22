from datetime import UTC, datetime, timedelta

from weatherml.common.audit import track_run
from weatherml.db.models import Location, WeatherFeature, WeatherObservation
from weatherml.features.pipeline import build_features_for_location
from weatherml.features.repository import upsert_features


def _seed_observations(db_session, location_id: int, run_id, base: datetime):
    for i, temp in enumerate([10.0, 12.0, 14.0]):
        db_session.add(
            WeatherObservation(
                location_id=location_id,
                observation_time=base + timedelta(hours=i),
                temperature_c=temp,
                humidity_pct=60,
                pressure_hpa=1013.0,
                wind_speed_kph=10.0,
                precip_mm=0.0,
                ingestion_run_id=run_id,
            )
        )
    db_session.commit()


def test_build_and_upsert_features_roundtrip(db_session):
    location = db_session.query(Location).filter_by(location_key="london_gb").one()
    base = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

    with track_run(db_session, dag_id="test", task_id="test") as run:
        _seed_observations(db_session, location.location_id, run.run_id, base)
    db_session.commit()

    row = build_features_for_location(
        db_session, location.location_id, as_of=base + timedelta(hours=2)
    )
    assert row is not None
    assert row["feature_time"] == base + timedelta(hours=2)
    assert row["lag_temp_1h"] == 12.0

    upsert_features(db_session, row)
    db_session.commit()

    stored = (
        db_session.query(WeatherFeature)
        .filter_by(location_id=location.location_id, feature_time=base + timedelta(hours=2))
        .one()
    )
    assert float(stored.lag_temp_1h) == 12.0

    # Re-running for the same feature_time upserts rather than duplicating.
    row2 = build_features_for_location(
        db_session, location.location_id, as_of=base + timedelta(hours=2)
    )
    upsert_features(db_session, row2)
    db_session.commit()

    count = (
        db_session.query(WeatherFeature)
        .filter_by(location_id=location.location_id, feature_time=base + timedelta(hours=2))
        .count()
    )
    assert count == 1


def test_no_data_returns_none(db_session):
    location = db_session.query(Location).filter_by(location_key="sydney_au").one()
    result = build_features_for_location(db_session, location.location_id, as_of=datetime.now(UTC))
    assert result is None
