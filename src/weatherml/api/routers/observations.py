from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from weatherml.api.deps import get_db
from weatherml.api.schemas import ObservationOut
from weatherml.db.models import WeatherObservation

router = APIRouter(tags=["observations"])

MAX_LIMIT = 1000


@router.get("/observations/{location_id}/latest", response_model=ObservationOut)
def latest_observation(location_id: int, db: Session = Depends(get_db)):
    stmt = (
        select(WeatherObservation)
        .where(WeatherObservation.location_id == location_id)
        .order_by(WeatherObservation.observation_time.desc())
        .limit(1)
    )
    obs = db.scalars(stmt).first()
    if obs is None:
        raise HTTPException(status_code=404, detail="no observations for this location")
    return obs


@router.get("/observations/{location_id}", response_model=list[ObservationOut])
def observation_history(
    location_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=100, le=MAX_LIMIT),
    db: Session = Depends(get_db),
):
    stmt = select(WeatherObservation).where(WeatherObservation.location_id == location_id)
    if start is not None:
        stmt = stmt.where(WeatherObservation.observation_time >= start)
    if end is not None:
        stmt = stmt.where(WeatherObservation.observation_time <= end)
    stmt = stmt.order_by(WeatherObservation.observation_time.desc()).limit(limit)
    return list(db.scalars(stmt))
