"""seed 5 curated locations

Revision ID: 6744b6766fa1
Revises: 6fc758da09b3
Create Date: 2026-09-22 14:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6744b6766fa1"
down_revision: str | None = "6fc758da09b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Deliberately diverse hemisphere/latitude/climate spread so the forecasting
# model sees varied seasonal and diurnal patterns rather than one climate.
# lat/lon (not display_name) is what the ingestion client sends to
# weatherstack's query param, since city names alone are ambiguous
# (e.g. "London" could resolve to London, Ontario).
LOCATIONS = [
    {
        "location_key": "new_york_us",
        "display_name": "New York",
        "country_code": "US",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "timezone": "America/New_York",
    },
    {
        "location_key": "london_gb",
        "display_name": "London",
        "country_code": "GB",
        "latitude": 51.5074,
        "longitude": -0.1278,
        "timezone": "Europe/London",
    },
    {
        "location_key": "tokyo_jp",
        "display_name": "Tokyo",
        "country_code": "JP",
        "latitude": 35.6762,
        "longitude": 139.6503,
        "timezone": "Asia/Tokyo",
    },
    {
        "location_key": "lagos_ng",
        "display_name": "Lagos",
        "country_code": "NG",
        "latitude": 6.5244,
        "longitude": 3.3792,
        "timezone": "Africa/Lagos",
    },
    {
        "location_key": "sydney_au",
        "display_name": "Sydney",
        "country_code": "AU",
        "latitude": -33.8688,
        "longitude": 151.2093,
        "timezone": "Australia/Sydney",
    },
]

locations_table = sa.table(
    "locations",
    sa.column("location_key", sa.String),
    sa.column("display_name", sa.String),
    sa.column("country_code", sa.String),
    sa.column("latitude", sa.Numeric),
    sa.column("longitude", sa.Numeric),
    sa.column("timezone", sa.String),
    sa.column("is_active", sa.Boolean),
    schema="core",
)


def upgrade() -> None:
    op.bulk_insert(
        locations_table,
        [{**loc, "is_active": True} for loc in LOCATIONS],
    )


def downgrade() -> None:
    keys = tuple(loc["location_key"] for loc in LOCATIONS)
    op.execute(
        sa.text("DELETE FROM core.locations WHERE location_key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": keys},
    )
