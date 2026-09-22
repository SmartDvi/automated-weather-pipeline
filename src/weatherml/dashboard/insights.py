"""Enriches raw observation rows (as returned by `GET /observations/{id}`)
with the same derived signals `weatherml.features.pipeline` computes for
model training — heat index, dew point, wind chill, pressure trend, storm
indicator — by calling the exact same pure functions in
`weatherml.features.functions`. The dashboard never redefines this math, it
just applies it to whatever window of history it already fetched for the
chart, purely for display in the observations grid.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from weatherml.features import functions as f

LOOKBACK_1H = timedelta(hours=1)
# Matches ROLLING_WINDOW_PRESSURE in features/pipeline.py
PRESSURE_TREND_WINDOW = timedelta(hours=3)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _value_at_or_before(rows: list[dict], index: int, field: str, target_time: datetime):
    for i in range(index, -1, -1):
        if rows[i]["_time"] <= target_time:
            return rows[i][field]
    return None


def enrich_observations(history: list[dict]) -> list[dict]:
    """`history` is a list of ObservationOut dicts, any order. Returns rows
    (newest first) with the original fields plus derived ones; safe on an
    empty or single-row history (derived fields just come back None).
    """
    rows = sorted(history, key=lambda r: r["observation_time"])
    for row in rows:
        row["_time"] = _parse_time(row["observation_time"])

    enriched = []
    for i, row in enumerate(rows):
        t = row["_time"]
        temp = row["temperature_c"]
        humidity = row["humidity_pct"]
        wind = row["wind_speed_kph"]
        precip = row["precip_mm"]

        temp_1h_ago = _value_at_or_before(rows, i, "temperature_c", t - LOOKBACK_1H)

        window = [r for r in rows[: i + 1] if t - PRESSURE_TREND_WINDOW <= r["_time"]]
        pressure_trend_3h = f.pressure_trend(
            [r["_time"] for r in window],
            [r["pressure_hpa"] for r in window],
        )

        enriched.append(
            {
                **{k: v for k, v in row.items() if k != "_time"},
                "heat_index_c": f.heat_index_c(temp, humidity),
                "dew_point_c": f.dew_point_c(temp, humidity),
                "wind_chill_c": f.wind_chill_c(temp, wind),
                "temp_rate_of_change_1h": f.rate_of_change(temp, temp_1h_ago),
                "pressure_trend_3h": pressure_trend_3h,
                "storm_risk": f.storm_indicator(pressure_trend_3h, wind, precip),
            }
        )

    enriched.reverse()  # newest first
    return enriched
