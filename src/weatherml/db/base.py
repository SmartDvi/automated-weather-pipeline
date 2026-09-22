from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model across the raw/core/features/ops schemas.

    Table-level `schema=` is set per-model (see models.py) rather than here,
    since a single Postgres database (`weather_db`) hosts all four logical
    schemas side by side.
    """

    # Every plain `Mapped[datetime]` column maps to TIMESTAMPTZ, not
    # SQLAlchemy's bare-datetime default of TIMESTAMP WITHOUT TIME ZONE.
    # Every datetime this codebase produces is UTC-aware (see
    # weatherml.common.time); storing it in a non-tz column would let
    # Postgres silently reinterpret it in the session's local timezone.
    type_annotation_map = {datetime: DateTime(timezone=True)}
