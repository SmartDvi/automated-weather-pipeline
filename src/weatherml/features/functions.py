"""Pure, DB-free feature-computation functions — every one is a plain
function over scalars/tuples, unit-testable with synthetic inputs and no
database or Airflow dependency. This is where the "real life problems"
framing lives: these aren't arbitrary statistical transforms, they're the
specific derived quantities meteorologists and health agencies use to turn a
raw sensor reading into an actionable signal (is it dangerously hot, is a
storm coming, is the air safe to breathe).
"""

import math
from datetime import datetime


def heat_index_c(temp_c: float | None, humidity_pct: float | None) -> float | None:
    """NWS Rothfusz regression. Only meaningful (and only how the NWS defines
    it) at or above ~26.7C (80F) with humidity data present; below that the
    "feels like" effect of humidity on heat is negligible, so returning None
    rather than a misleading number is correct here, not a missing case.
    """
    if temp_c is None or humidity_pct is None or temp_c < 26.7:
        return None

    t_f = temp_c * 9 / 5 + 32
    r = humidity_pct

    hi_f = (
        -42.379
        + 2.04901523 * t_f
        + 10.14333127 * r
        - 0.22475541 * t_f * r
        - 0.00683783 * t_f * t_f
        - 0.05481717 * r * r
        + 0.00122874 * t_f * t_f * r
        + 0.00085282 * t_f * r * r
        - 0.00000199 * t_f * t_f * r * r
    )
    return round((hi_f - 32) * 5 / 9, 2)


def dew_point_c(temp_c: float | None, humidity_pct: float | None) -> float | None:
    """Magnus-Tetens approximation. Undefined for humidity <= 0."""
    if temp_c is None or humidity_pct is None or humidity_pct <= 0:
        return None

    a, b = 17.62, 243.12
    gamma = (a * temp_c) / (b + temp_c) + math.log(humidity_pct / 100.0)
    return round((b * gamma) / (a - gamma), 2)


def wind_chill_c(temp_c: float | None, wind_kph: float | None) -> float | None:
    """Environment Canada / NWS formula. Only valid at <=10C with wind
    >=4.8kph — outside that range wind doesn't meaningfully change perceived
    cold via convective heat loss the way this formula models, so None
    (not a clamped or extrapolated value) is the correct output.
    """
    if temp_c is None or wind_kph is None or temp_c > 10 or wind_kph < 4.8:
        return None

    v_pow = wind_kph**0.16
    return round(13.12 + 0.6215 * temp_c - 11.37 * v_pow + 0.3965 * temp_c * v_pow, 2)


def rate_of_change(current_value: float | None, past_value: float | None) -> float | None:
    if current_value is None or past_value is None:
        return None
    return round(current_value - past_value, 3)


def pressure_trend(times: list[datetime], pressures: list[float]) -> float | None:
    """Linear slope (hPa/hour) over the given window via least squares. A
    falling trend (large negative slope) is the classic precursor signal for
    an approaching low-pressure system / storm; this is the feature
    `storm_indicator` below actually consumes.
    """
    points = [(t, p) for t, p in zip(times, pressures, strict=True) if p is not None]
    if len(points) < 2:
        return None

    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 3600.0 for t, _ in points]
    ys = [p for _, p in points]

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def cyclical_encode(dt: datetime) -> tuple[float, float, float, float]:
    """(hour_sin, hour_cos, doy_sin, doy_cos) — lets a model learn daily and
    seasonal periodicity (e.g. afternoon-warmer, summer-warmer) without
    discontinuities at midnight/year-end that a raw hour-of-day or
    day-of-year integer would introduce.
    """
    hour_frac = dt.hour + dt.minute / 60.0
    hour_angle = 2 * math.pi * hour_frac / 24.0
    doy_angle = 2 * math.pi * dt.timetuple().tm_yday / 365.25
    return (
        round(math.sin(hour_angle), 5),
        round(math.cos(hour_angle), 5),
        round(math.sin(doy_angle), 5),
        round(math.cos(doy_angle), 5),
    )


# Rough health-relevance weights, not a regulatory index: PM2.5 and PM10 (fine
# particulates) dominate acute health risk, O3/NO2/SO2 contribute less
# heavily at typical ambient concentrations, CO is deliberately excluded
# from the weighted sum here (its dangerous range is far above what these
# other pollutants' scales suggest and would dominate the composite).
_AQI_WEIGHTS = {"pm2_5": 0.35, "pm10": 0.20, "o3": 0.20, "no2": 0.15, "so2": 0.10}
# Rough "unhealthy" reference concentration (ug/m3) per pollutant, used only
# to normalize each pollutant onto a comparable 0-1+ scale before weighting.
_AQI_REFERENCE = {"pm2_5": 35.0, "pm10": 150.0, "o3": 100.0, "no2": 100.0, "so2": 75.0}


def aqi_composite_risk(
    pm2_5: float | None,
    pm10: float | None,
    o3: float | None,
    no2: float | None,
    so2: float | None,
) -> tuple[float | None, str | None]:
    """Weighted composite risk score (roughly 0-100+, unbounded above) and a
    bucketed label. This is a documented heuristic for cross-pollutant
    comparison and alerting, NOT the official US EPA AQI or any regulatory
    index — weatherstack's own `us-epa-index`/`gb-defra-index` fields are
    kept as-is in core.weather_observations for that.
    """
    values = {"pm2_5": pm2_5, "pm10": pm10, "o3": o3, "no2": no2, "so2": so2}
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        return None, None

    total_weight = sum(_AQI_WEIGHTS[k] for k in present)
    score = (
        100
        * sum(_AQI_WEIGHTS[k] * (present[k] / _AQI_REFERENCE[k]) for k in present)
        / total_weight
    )
    score = round(score, 2)

    if score < 25:
        level = "good"
    elif score < 50:
        level = "moderate"
    elif score < 100:
        level = "unhealthy_sensitive"
    elif score < 150:
        level = "unhealthy"
    else:
        level = "hazardous"
    return score, level


def storm_indicator(
    pressure_trend_hpa_per_hr: float | None,
    wind_speed_kph: float | None,
    precip_mm: float | None,
) -> bool | None:
    """Rule-based storm/severe-weather flag: a rapidly falling pressure
    trend combined with either strong wind or active precipitation is the
    textbook signature of an approaching or active storm system. Deliberately
    simple and inspectable rather than learned, since this doubles as an
    alerting signal that needs to be explainable.
    """
    if pressure_trend_hpa_per_hr is None:
        return None
    falling_fast = pressure_trend_hpa_per_hr <= -1.0
    windy = (wind_speed_kph or 0) >= 30
    raining = (precip_mm or 0) >= 2
    return bool(falling_fast and (windy or raining))
