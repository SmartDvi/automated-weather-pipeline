from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from weatherml.db.models import WeatherFeature


def upsert_features(session: Session, feature_row: dict) -> None:
    """INSERT ... ON CONFLICT (location_id, feature_time) DO UPDATE — mirrors
    the ingestion upsert pattern so re-running the hourly DAG for a slot
    that's already computed updates in place.
    """
    stmt = pg_insert(WeatherFeature).values(**feature_row)
    update_cols = {
        k: stmt.excluded[k] for k in feature_row if k not in ("location_id", "feature_time")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["location_id", "feature_time"],
        set_=update_cols,
    )
    session.execute(stmt)
