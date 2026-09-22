import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from weatherml.db.models import Location, WeatherObservation, WeatherObservationRaw


def get_location(session: Session, location_id: int) -> Location | None:
    return session.get(Location, location_id)


def list_active_locations(session: Session) -> list[Location]:
    return list(session.scalars(select(Location).where(Location.is_active.is_(True))))


def insert_raw(
    session: Session,
    *,
    location_id: int,
    ingestion_run_id: uuid.UUID,
    http_status: int | None,
    is_error: bool,
    error_code: int | None,
    error_info: str | None,
    payload: dict,
) -> WeatherObservationRaw:
    raw = WeatherObservationRaw(
        location_id=location_id,
        ingestion_run_id=ingestion_run_id,
        http_status=http_status,
        is_error=is_error,
        error_code=error_code,
        error_info=error_info,
        payload=payload,
    )
    session.add(raw)
    session.flush()
    return raw


def upsert_observation(
    session: Session,
    *,
    location_id: int,
    observation_time: datetime,
    fields: dict,
    raw_observation_id: int,
    ingestion_run_id: uuid.UUID,
) -> None:
    """INSERT ... ON CONFLICT (location_id, observation_time) DO UPDATE — the
    idempotency mechanism documented on WeatherObservation: rerunning
    ingestion for a slot that already landed updates in place rather than
    duplicating.
    """
    values = {
        "location_id": location_id,
        "observation_time": observation_time,
        "raw_observation_id": raw_observation_id,
        "ingestion_run_id": ingestion_run_id,
        **fields,
    }
    stmt = pg_insert(WeatherObservation).values(**values)
    update_cols = {
        k: stmt.excluded[k]
        for k in {**fields, "raw_observation_id": None, "ingestion_run_id": None}
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["location_id", "observation_time"],
        set_=update_cols,
    )
    session.execute(stmt)
