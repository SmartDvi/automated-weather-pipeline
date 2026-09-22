"""compute_feature_row is pure over an already-loaded DataFrame (no DB), so
the no-leakage guarantee is directly testable here without a database —
build_features_for_location just adds the `observation_time <= as_of` SQL
bound around this same function.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd

from weatherml.features.pipeline import _COLUMNS, compute_feature_row


def _row(t: datetime, temp: float, humidity: float = 60.0, pressure: float = 1013.0):
    return {
        "observation_time": t,
        "temperature_c": temp,
        "humidity_pct": humidity,
        "pressure_hpa": pressure,
        "wind_speed_kph": 10.0,
        "precip_mm": 0.0,
        "aqi_pm2_5": 5.0,
        "aqi_pm10": 10.0,
        "aqi_o3": 20.0,
        "aqi_no2": 10.0,
        "aqi_so2": 2.0,
    }


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_COLUMNS)


def test_empty_dataframe_returns_none():
    assert compute_feature_row(_frame([])) is None


def test_anchors_on_latest_row():
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    rows = [_row(base, temp=10.0), _row(base + timedelta(hours=1), temp=15.0)]
    result = compute_feature_row(_frame(rows))
    assert result["feature_time"] == base + timedelta(hours=1)


def test_future_rows_never_influence_the_feature_row():
    """The no-leakage guarantee: rows after the chosen as_of must not affect
    lag/rolling/rate-of-change features, even if present in the input frame.
    """
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    rows = [
        _row(base - timedelta(hours=1), temp=10.0),
        _row(base, temp=20.0),
        _row(base + timedelta(hours=1), temp=999.0),  # future — must be excluded
    ]
    result = compute_feature_row(_frame(rows), as_of=base)
    assert result["feature_time"] == base
    assert result["lag_temp_1h"] == 10.0
    assert result["rolling_mean_temp_3h"] < 100  # would be huge if 999.0 leaked in


def test_lag_features_none_without_enough_history():
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    result = compute_feature_row(_frame([_row(base, temp=15.0)]))
    assert result["lag_temp_1h"] is None
    assert result["lag_temp_3h"] is None
    assert result["lag_temp_6h"] is None


def test_temp_rate_of_change_uses_lag_1h():
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    rows = [_row(base - timedelta(hours=1), temp=10.0), _row(base, temp=16.0)]
    result = compute_feature_row(_frame(rows))
    assert result["temp_rate_of_change_1h"] == 6.0


def test_cyclical_features_always_present():
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    result = compute_feature_row(_frame([_row(base, temp=15.0)]))
    assert result["hour_sin"] is not None
    assert result["hour_cos"] is not None
    assert result["doy_sin"] is not None
    assert result["doy_cos"] is not None
