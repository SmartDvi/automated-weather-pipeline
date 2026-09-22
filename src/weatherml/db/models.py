"""ORM models for every table in weather_db, across four logical schemas:

- core:     stable reference/dimension + cleaned fact data (locations, observations)
- raw:      append-only landing zone for every API poll attempt (audit trail)
- features: engineered, model-ready feature rows
- ops:      operational metadata (pipeline run audit log, data quality results,
            online prediction log)

See migrations/versions/0001_initial_schema.py for the DDL these generate.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from weatherml.db.base import Base

# --------------------------------------------------------------------------- #
# ops.pipeline_runs — created first: raw/core inserts within a task reference it
# --------------------------------------------------------------------------- #


class PipelineRun(Base):
    """One row per Airflow task execution. Opened `running` at task start via
    `weatherml.common.audit.track_run`, closed `success`/`failed` at task end.
    Gives raw/core inserts a valid run_id to attribute rows to, and is the
    audit trail an operator checks in `ops.pipeline_runs` when a DAG fails.
    """

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed')", name="ck_pipeline_run_status"
        ),
        Index("ix_pipeline_runs_dag_started", "dag_id", "started_at"),
        Index("ix_pipeline_runs_status", "status"),
        {"schema": "ops"},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dag_id: Mapped[str] = mapped_column(String(200))
    task_id: Mapped[str] = mapped_column(String(200))
    dag_run_id: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(20), default="running")
    rows_processed: Mapped[int | None]
    error_message: Mapped[str | None]
    extra: Mapped[dict | None] = mapped_column(JSONB)


# --------------------------------------------------------------------------- #
# core.locations
# --------------------------------------------------------------------------- #


class Location(Base):
    """Dimension table for ingested cities. Ingestion/feature/training DAGs all
    read `WHERE is_active` at execution time instead of hardcoding a city list,
    so adding/removing a location is an operational data change, not a deploy.
    """

    __tablename__ = "locations"
    __table_args__ = {"schema": "core"}

    location_id: Mapped[int] = mapped_column(primary_key=True)
    location_key: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    country_code: Mapped[str] = mapped_column(String(2))
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# --------------------------------------------------------------------------- #
# raw.weather_observations_raw
# --------------------------------------------------------------------------- #


class WeatherObservationRaw(Base):
    """Append-only landing table: one row per API poll attempt, success or
    failure, full response body preserved as JSONB. Deliberately has no
    uniqueness constraint — it IS the raw traffic audit trail. Idempotency for
    downstream consumers lives one layer up, in core.weather_observations.
    """

    __tablename__ = "weather_observations_raw"
    __table_args__ = (
        Index("ix_raw_obs_location_fetched", "location_id", "fetched_at"),
        Index("ix_raw_obs_is_error", "is_error", postgresql_where=text("is_error")),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("core.locations.location_id"))
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())
    source: Mapped[str] = mapped_column(String(50), default="weatherstack")
    http_status: Mapped[int | None]
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[int | None]
    error_info: Mapped[str | None]
    payload: Mapped[dict] = mapped_column(JSONB)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops.pipeline_runs.run_id")
    )


# --------------------------------------------------------------------------- #
# core.weather_observations
# --------------------------------------------------------------------------- #


class WeatherObservation(Base):
    """Cleaned, typed fact table — one row per (location, observation_time).

    UNIQUE(location_id, observation_time) is the idempotency key: ingestion
    upserts ON CONFLICT on this pair, so re-running the DAG for a slot that
    already landed is a no-op update rather than a duplicate row. The same
    composite index serves the dominant read pattern (recent history for a
    location, time-ordered) used by feature engineering and the API.
    """

    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint("location_id", "observation_time", name="uq_core_obs_location_time"),
        Index("ix_core_obs_location_time", "location_id", "observation_time"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("core.locations.location_id"))
    observation_time: Mapped[datetime]

    temperature_c: Mapped[float | None] = mapped_column(Numeric(5, 2))
    feelslike_c: Mapped[float | None] = mapped_column(Numeric(5, 2))
    humidity_pct: Mapped[int | None] = mapped_column(SmallInteger)
    pressure_hpa: Mapped[float | None] = mapped_column(Numeric(6, 2))
    wind_speed_kph: Mapped[float | None] = mapped_column(Numeric(5, 2))
    wind_degree: Mapped[int | None] = mapped_column(SmallInteger)
    wind_dir: Mapped[str | None] = mapped_column(String(10))
    precip_mm: Mapped[float | None] = mapped_column(Numeric(5, 2))
    cloudcover_pct: Mapped[int | None] = mapped_column(SmallInteger)
    uv_index: Mapped[int | None] = mapped_column(SmallInteger)
    visibility_km: Mapped[float | None] = mapped_column(Numeric(5, 2))
    weather_code: Mapped[int | None] = mapped_column(SmallInteger)
    weather_description: Mapped[str | None] = mapped_column(String(200))
    is_day: Mapped[bool | None]

    sunrise: Mapped[str | None] = mapped_column(Time)
    sunset: Mapped[str | None] = mapped_column(Time)
    moon_phase: Mapped[str | None] = mapped_column(String(50))
    moon_illumination_pct: Mapped[int | None] = mapped_column(SmallInteger)

    aqi_co: Mapped[float | None] = mapped_column(Numeric(8, 3))
    aqi_no2: Mapped[float | None] = mapped_column(Numeric(8, 3))
    aqi_o3: Mapped[float | None] = mapped_column(Numeric(8, 3))
    aqi_so2: Mapped[float | None] = mapped_column(Numeric(8, 3))
    aqi_pm2_5: Mapped[float | None] = mapped_column(Numeric(8, 3))
    aqi_pm10: Mapped[float | None] = mapped_column(Numeric(8, 3))
    aqi_us_epa_index: Mapped[int | None] = mapped_column(SmallInteger)
    aqi_gb_defra_index: Mapped[int | None] = mapped_column(SmallInteger)

    raw_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw.weather_observations_raw.id")
    )
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops.pipeline_runs.run_id")
    )
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())

    location: Mapped["Location"] = relationship()


# --------------------------------------------------------------------------- #
# features.weather_features
# --------------------------------------------------------------------------- #


class WeatherFeature(Base):
    """Engineered, model-ready feature row for (location, feature_time).

    Deliberately has NO stored label/target column: the prediction target
    (temperature N hours after feature_time) is constructed at training time
    by joining forward against core.weather_observations. That join is
    structurally incapable of pulling data from before feature_time, so there
    is no separate label-backfill job and no way to accidentally leak future
    information into a feature row.
    """

    __tablename__ = "weather_features"
    __table_args__ = (
        UniqueConstraint("location_id", "feature_time", name="uq_features_location_time"),
        Index("ix_features_location_time", "location_id", "feature_time"),
        {"schema": "features"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("core.locations.location_id"))
    feature_time: Mapped[datetime]
    feature_set_version: Mapped[int] = mapped_column(SmallInteger, default=1)

    lag_temp_1h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    lag_temp_3h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    lag_temp_6h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    rolling_mean_temp_3h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    rolling_std_temp_3h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    rolling_mean_temp_6h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    temp_rate_of_change_1h: Mapped[float | None] = mapped_column(Numeric(6, 3))

    pressure_delta_1h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    pressure_trend_3h: Mapped[float | None] = mapped_column(Numeric(6, 3))

    lag_humidity_1h: Mapped[float | None] = mapped_column(Numeric(6, 3))
    rolling_mean_humidity_3h: Mapped[float | None] = mapped_column(Numeric(6, 3))

    hour_sin: Mapped[float | None] = mapped_column(Numeric(6, 5))
    hour_cos: Mapped[float | None] = mapped_column(Numeric(6, 5))
    doy_sin: Mapped[float | None] = mapped_column(Numeric(6, 5))
    doy_cos: Mapped[float | None] = mapped_column(Numeric(6, 5))

    heat_index_c: Mapped[float | None] = mapped_column(Numeric(5, 2))
    dew_point_c: Mapped[float | None] = mapped_column(Numeric(5, 2))
    wind_chill_c: Mapped[float | None] = mapped_column(Numeric(5, 2))

    aqi_composite_risk_score: Mapped[float | None] = mapped_column(Numeric(6, 3))
    aqi_risk_level: Mapped[str | None] = mapped_column(String(20))
    storm_indicator: Mapped[bool | None]

    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())


# --------------------------------------------------------------------------- #
# ops.data_quality_checks
# --------------------------------------------------------------------------- #


class DataQualityCheck(Base):
    """One row per validation check per run. The partial index on
    (severity, passed) WHERE NOT passed directly serves the alert-hook query
    `weatherml.quality.service` runs after each check batch.
    """

    __tablename__ = "data_quality_checks"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_dq_severity"),
        Index("ix_dq_checked_at", "checked_at"),
        Index("ix_dq_failed_critical", "severity", "passed", postgresql_where=text("NOT passed")),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ops.pipeline_runs.run_id")
    )
    check_name: Mapped[str] = mapped_column(String(100))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("core.locations.location_id"))
    severity: Mapped[str] = mapped_column(String(20))
    passed: Mapped[bool]
    details: Mapped[dict | None] = mapped_column(JSONB)
    checked_at: Mapped[datetime] = mapped_column(server_default=func.now())


# --------------------------------------------------------------------------- #
# ops.model_predictions
# --------------------------------------------------------------------------- #


class ModelPrediction(Base):
    """Online monitoring log: every prediction served by POST /predict is
    recorded here. `actual_temp_c` stays NULL until a later reconciliation job
    (documented as v1.1, not built yet) backfills it once the horizon elapses,
    enabling future drift/accuracy-over-time tracking without a migration.
    """

    __tablename__ = "model_predictions"
    __table_args__ = (
        Index("ix_predictions_location_time", "location_id", "predicted_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("core.locations.location_id"))
    predicted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    horizon_hours: Mapped[int] = mapped_column(SmallInteger)
    predicted_temp_c: Mapped[float] = mapped_column(Numeric(5, 2))
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(20))
    model_alias: Mapped[str] = mapped_column(String(20))
    input_feature_time: Mapped[datetime | None]
    actual_temp_c: Mapped[float | None] = mapped_column(Numeric(5, 2))
