import logging
import statistics
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from weatherml.common.audit import track_run
from weatherml.config import get_settings
from weatherml.db.models import WeatherObservation
from weatherml.db.session import session_scope

from . import functions as f
from .repository import upsert_features

logger = logging.getLogger(__name__)

LAG_HOURS = (1, 3, 6)
ROLLING_WINDOWS_TEMP = (3, 6)
ROLLING_WINDOW_HUMIDITY = 3
ROLLING_WINDOW_PRESSURE = 3

_COLUMNS = (
    "observation_time",
    "temperature_c",
    "humidity_pct",
    "pressure_hpa",
    "wind_speed_kph",
    "precip_mm",
    "aqi_pm2_5",
    "aqi_pm10",
    "aqi_o3",
    "aqi_no2",
    "aqi_so2",
)


def _load_observations(
    session: Session, location_id: int, as_of: datetime, lookback_hours: int
) -> pd.DataFrame:
    window_start = as_of - timedelta(hours=lookback_hours)
    stmt = (
        select(*(getattr(WeatherObservation, c) for c in _COLUMNS))
        .where(WeatherObservation.location_id == location_id)
        .where(WeatherObservation.observation_time <= as_of)
        .where(WeatherObservation.observation_time >= window_start)
        .order_by(WeatherObservation.observation_time.asc())
    )
    rows = session.execute(stmt).all()
    return pd.DataFrame(rows, columns=_COLUMNS)


def _as_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _value_at_or_before(df: pd.DataFrame, column: str, target_time: datetime) -> float | None:
    subset = df[df["observation_time"] <= target_time]
    if subset.empty:
        return None
    return _as_float(subset.iloc[-1][column])


def _window(df: pd.DataFrame, end_time: datetime, window_hours: float) -> pd.DataFrame:
    start_time = end_time - timedelta(hours=window_hours)
    return df[(df["observation_time"] >= start_time) & (df["observation_time"] <= end_time)]


def compute_feature_row(df: pd.DataFrame, as_of: datetime | None = None) -> dict | None:
    """Pure(ish) core of feature computation: given an already-loaded,
    ascending-by-time DataFrame of one location's observations, compute one
    feature row anchored on the latest observation at or before `as_of`.
    Split out from build_features_for_location so the no-leakage guarantee
    (the caller controls exactly what rows `df` contains) is directly
    testable without a database.
    """
    if df.empty:
        return None

    if as_of is not None:
        df = df[df["observation_time"] <= as_of]
        if df.empty:
            return None

    anchor = df.iloc[-1]
    anchor_time = anchor["observation_time"]
    if hasattr(anchor_time, "to_pydatetime"):
        anchor_time = anchor_time.to_pydatetime()

    anchor_temp = _as_float(anchor["temperature_c"])
    anchor_humidity = _as_float(anchor["humidity_pct"])
    anchor_pressure = _as_float(anchor["pressure_hpa"])
    anchor_wind = _as_float(anchor["wind_speed_kph"])
    anchor_precip = _as_float(anchor["precip_mm"])

    lag_temp = {
        h: _value_at_or_before(df, "temperature_c", anchor_time - timedelta(hours=h))
        for h in LAG_HOURS
    }
    lag_humidity_1h = _value_at_or_before(df, "humidity_pct", anchor_time - timedelta(hours=1))
    pressure_1h_ago = _value_at_or_before(df, "pressure_hpa", anchor_time - timedelta(hours=1))

    rolling_mean = {}
    for w in ROLLING_WINDOWS_TEMP:
        vals = [_as_float(v) for v in _window(df, anchor_time, w)["temperature_c"]]
        vals = [v for v in vals if v is not None]
        rolling_mean[w] = round(statistics.mean(vals), 3) if vals else None

    temp_vals_3h = [
        v
        for v in (_as_float(v) for v in _window(df, anchor_time, 3)["temperature_c"])
        if v is not None
    ]
    rolling_std_temp_3h = (
        round(statistics.pstdev(temp_vals_3h), 3) if len(temp_vals_3h) >= 2 else None
    )

    humidity_vals = [
        v
        for v in (
            _as_float(v) for v in _window(df, anchor_time, ROLLING_WINDOW_HUMIDITY)["humidity_pct"]
        )
        if v is not None
    ]
    rolling_mean_humidity_3h = round(statistics.mean(humidity_vals), 3) if humidity_vals else None

    pressure_window = _window(df, anchor_time, ROLLING_WINDOW_PRESSURE)
    pressure_trend_3h = f.pressure_trend(
        list(pressure_window["observation_time"]),
        [_as_float(v) for v in pressure_window["pressure_hpa"]],
    )

    hour_sin, hour_cos, doy_sin, doy_cos = f.cyclical_encode(anchor_time)
    aqi_score, aqi_level = f.aqi_composite_risk(
        _as_float(anchor["aqi_pm2_5"]),
        _as_float(anchor["aqi_pm10"]),
        _as_float(anchor["aqi_o3"]),
        _as_float(anchor["aqi_no2"]),
        _as_float(anchor["aqi_so2"]),
    )

    return {
        "feature_time": anchor_time,
        "lag_temp_1h": lag_temp[1],
        "lag_temp_3h": lag_temp[3],
        "lag_temp_6h": lag_temp[6],
        "rolling_mean_temp_3h": rolling_mean[3],
        "rolling_std_temp_3h": rolling_std_temp_3h,
        "rolling_mean_temp_6h": rolling_mean[6],
        "temp_rate_of_change_1h": f.rate_of_change(anchor_temp, lag_temp[1]),
        "pressure_delta_1h": f.rate_of_change(anchor_pressure, pressure_1h_ago),
        "pressure_trend_3h": pressure_trend_3h,
        "lag_humidity_1h": lag_humidity_1h,
        "rolling_mean_humidity_3h": rolling_mean_humidity_3h,
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "doy_sin": doy_sin,
        "doy_cos": doy_cos,
        "heat_index_c": f.heat_index_c(anchor_temp, anchor_humidity),
        "dew_point_c": f.dew_point_c(anchor_temp, anchor_humidity),
        "wind_chill_c": f.wind_chill_c(anchor_temp, anchor_wind),
        "aqi_composite_risk_score": aqi_score,
        "aqi_risk_level": aqi_level,
        "storm_indicator": f.storm_indicator(pressure_trend_3h, anchor_wind, anchor_precip),
    }


def build_features_for_location(
    session: Session, location_id: int, as_of: datetime | None = None
) -> dict | None:
    """Loads a bounded lookback window (observation_time <= as_of — the
    leakage guard) and delegates to compute_feature_row. Returns None if the
    location has no observations in the window yet.
    """
    settings = get_settings()
    as_of = as_of or datetime.now(UTC)
    lookback_hours = max(settings.feature_lookback_hours, max(LAG_HOURS + ROLLING_WINDOWS_TEMP))
    df = _load_observations(session, location_id, as_of, lookback_hours)
    row = compute_feature_row(df)
    if row is None:
        return None
    return {"location_id": location_id, **row}


def build_and_store_features(location_id: int, dag_run_id: str | None = None) -> bool:
    """Computes and upserts the latest feature row for one location. Called
    by the CLI (see weatherml/cli.py) from the hourly feature_engineering DAG.
    Returns False (without raising) when there's simply no data yet for a
    location — not an error, just nothing to do this cycle.
    """
    with (
        session_scope() as session,
        track_run(
            session,
            dag_id="feature_engineering",
            task_id=f"features_{location_id}",
            dag_run_id=dag_run_id,
        ) as run,
    ):
        row = build_features_for_location(session, location_id)
        if row is None:
            run.rows_processed = 0
            logger.info("no_observations_for_features", extra={"location_id": location_id})
            return False
        upsert_features(session, row)
        run.rows_processed = 1
        logger.info(
            "features_built",
            extra={"location_id": location_id, "feature_time": str(row["feature_time"])},
        )
        return True
