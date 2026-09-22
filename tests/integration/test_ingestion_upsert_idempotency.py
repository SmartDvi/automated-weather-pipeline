from datetime import UTC, datetime

from weatherml.common.audit import track_run
from weatherml.db.models import Location
from weatherml.ingestion.repository import insert_raw, upsert_observation


def test_rerunning_ingestion_for_same_slot_updates_not_duplicates(db_session):
    location = db_session.query(Location).filter_by(location_key="new_york_us").one()
    observation_time = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    with track_run(db_session, dag_id="test", task_id="test") as run:
        raw1 = insert_raw(
            db_session,
            location_id=location.location_id,
            ingestion_run_id=run.run_id,
            http_status=200,
            is_error=False,
            error_code=None,
            error_info=None,
            payload={"current": {"temperature": 10}},
        )
        upsert_observation(
            db_session,
            location_id=location.location_id,
            observation_time=observation_time,
            fields={"temperature_c": 10.0, "humidity_pct": 50},
            raw_observation_id=raw1.id,
            ingestion_run_id=run.run_id,
        )
    db_session.commit()

    # Rerun for the exact same (location_id, observation_time) with a
    # different value — simulates the DAG retrying/rerunning the same slot.
    with track_run(db_session, dag_id="test", task_id="test") as run2:
        raw2 = insert_raw(
            db_session,
            location_id=location.location_id,
            ingestion_run_id=run2.run_id,
            http_status=200,
            is_error=False,
            error_code=None,
            error_info=None,
            payload={"current": {"temperature": 12}},
        )
        upsert_observation(
            db_session,
            location_id=location.location_id,
            observation_time=observation_time,
            fields={"temperature_c": 12.0, "humidity_pct": 55},
            raw_observation_id=raw2.id,
            ingestion_run_id=run2.run_id,
        )
    db_session.commit()

    from weatherml.db.models import WeatherObservation

    rows = (
        db_session.query(WeatherObservation)
        .filter_by(location_id=location.location_id, observation_time=observation_time)
        .all()
    )
    assert len(rows) == 1
    assert float(rows[0].temperature_c) == 12.0
    assert rows[0].humidity_pct == 55

    # raw.weather_observations_raw is append-only — both attempts are audit-logged
    from weatherml.db.models import WeatherObservationRaw

    raw_rows = (
        db_session.query(WeatherObservationRaw).filter_by(location_id=location.location_id).all()
    )
    assert len(raw_rows) == 2
