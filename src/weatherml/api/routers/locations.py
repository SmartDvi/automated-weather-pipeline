from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from weatherml.api.deps import get_db
from weatherml.api.schemas import LocationOut
from weatherml.db.models import Location

router = APIRouter(tags=["locations"])


@router.get("/locations", response_model=list[LocationOut])
def list_locations(db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Location).where(Location.is_active.is_(True)).order_by(Location.location_id)
        )
    )
