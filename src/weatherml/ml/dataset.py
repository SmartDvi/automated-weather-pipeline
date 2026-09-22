import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from weatherml.db.models import Location, WeatherFeature, WeatherObservation

# storm_indicator (bool) and aqi_risk_level (categorical) are meaningful as
# standalone alerting signals (see features/functions.py) but are left out of
# the v1 numeric regressor's inputs — encoding them is a natural next
# iteration, not a correctness requirement for a first working model.
FEATURE_COLUMNS = [
    "lag_temp_1h",
    "lag_temp_3h",
    "lag_temp_6h",
    "rolling_mean_temp_3h",
    "rolling_std_temp_3h",
    "rolling_mean_temp_6h",
    "temp_rate_of_change_1h",
    "pressure_delta_1h",
    "pressure_trend_3h",
    "lag_humidity_1h",
    "rolling_mean_humidity_3h",
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
    "heat_index_c",
    "dew_point_c",
    "wind_chill_c",
    "aqi_composite_risk_score",
]

# Real observation timestamps drift a few minutes off any exact grid (the
# underlying station's own update cadence, retries, etc.), so the label join
# below uses a tolerance-based nearest match (pd.merge_asof) rather than an
# exact-equality join on `feature_time + horizon`, which would silently match
# almost nothing. The leakage guarantee this preserves is what matters: the
# matched observation can only be at or after feature_time (never before),
# since it's drawn from a target_time computed strictly forward from it.
TARGET_MATCH_TOLERANCE = pd.Timedelta(minutes=12)


def _load_features(session: Session, location_id: int) -> pd.DataFrame:
    cols = [WeatherFeature.feature_time, *(getattr(WeatherFeature, c) for c in FEATURE_COLUMNS)]
    stmt = (
        select(*cols)
        .where(WeatherFeature.location_id == location_id)
        .order_by(WeatherFeature.feature_time.asc())
    )
    rows = session.execute(stmt).all()
    df = pd.DataFrame(rows, columns=["feature_time", *FEATURE_COLUMNS])
    return df.astype({c: "float64" for c in FEATURE_COLUMNS}, errors="ignore")


def _load_observations(session: Session, location_id: int) -> pd.DataFrame:
    stmt = (
        select(WeatherObservation.observation_time, WeatherObservation.temperature_c)
        .where(WeatherObservation.location_id == location_id)
        .order_by(WeatherObservation.observation_time.asc())
    )
    rows = session.execute(stmt).all()
    return pd.DataFrame(rows, columns=["observation_time", "target_temp_c"])


def build_supervised_frame(
    features_df: pd.DataFrame, obs_df: pd.DataFrame, horizon_hours: int
) -> pd.DataFrame:
    """Joins each feature row to the observation nearest `feature_time +
    horizon_hours` (within TARGET_MATCH_TOLERANCE), dropping rows with no
    match. Pure function over two DataFrames — no DB access — so the
    no-leakage property is directly unit-testable with synthetic frames.
    """
    if features_df.empty or obs_df.empty:
        return pd.DataFrame(columns=[*FEATURE_COLUMNS, "feature_time", "target_temp_c"])

    df = features_df.copy()
    df["target_time"] = df["feature_time"] + pd.Timedelta(hours=horizon_hours)
    df = df.sort_values("target_time")
    obs_sorted = obs_df.sort_values("observation_time")

    merged = pd.merge_asof(
        df,
        obs_sorted,
        left_on="target_time",
        right_on="observation_time",
        direction="nearest",
        tolerance=TARGET_MATCH_TOLERANCE,
    )
    merged = merged.dropna(subset=["target_temp_c"])
    return merged.sort_values("feature_time").reset_index(drop=True)


def load_training_frame(
    session: Session, horizon_hours: int, location_ids: list[int] | None = None
) -> pd.DataFrame:
    """Supervised frame across every active location (or a specific subset),
    time-ordered by feature_time. Each row also carries `current_temp_c`
    (the anchor reading itself, useful as the persistence baseline's input)
    and `location_id`.
    """
    if location_ids is None:
        location_ids = [
            loc.location_id
            for loc in session.scalars(select(Location).where(Location.is_active.is_(True)))
        ]

    frames = []
    for location_id in location_ids:
        features_df = _load_features(session, location_id)
        obs_df = _load_observations(session, location_id)
        supervised = build_supervised_frame(features_df, obs_df, horizon_hours)
        if supervised.empty:
            continue
        # current_temp_c = the anchor's own temperature, needed by the
        # persistence baseline (predict temp(t+h) = temp(t)); recovered as
        # lag_temp_0 is trivially the same as "temp at feature_time itself"
        # which isn't stored in weather_features, so we re-derive it as the
        # observation nearest feature_time (0h offset).
        anchor_supervised = build_supervised_frame(features_df, obs_df, 0)
        supervised = supervised.merge(
            anchor_supervised[["feature_time", "target_temp_c"]].rename(
                columns={"target_temp_c": "current_temp_c"}
            ),
            on="feature_time",
            how="left",
        )
        supervised["location_id"] = location_id
        frames.append(supervised)

    if not frames:
        return pd.DataFrame(
            columns=[
                *FEATURE_COLUMNS,
                "feature_time",
                "target_temp_c",
                "current_temp_c",
                "location_id",
            ]
        )
    return pd.concat(frames, ignore_index=True).sort_values("feature_time").reset_index(drop=True)


def time_ordered_split(
    df: pd.DataFrame, test_size: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sorts by feature_time and slices — never shuffles. This is a time
    series: a random shuffle would let the model train on data from after
    points in its own test set, which is leakage even though no single row
    is corrupted.
    """
    df = df.sort_values("feature_time").reset_index(drop=True)
    split_idx = int(len(df) * (1 - test_size))
    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()
