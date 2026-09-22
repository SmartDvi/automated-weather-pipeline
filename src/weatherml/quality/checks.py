"""Pure validation functions — plain scalars/dataclasses in and out, no DB or
Airflow dependency, mirroring features/functions.py's testability story.
"""

from dataclasses import dataclass, field
from datetime import datetime

# Physically-plausible bounds, not climatological ones — wide enough to
# never false-positive on real weather, tight enough to catch a parsing bug
# or a sensor/API glitch (e.g. a stray 0 or a unit-conversion error).
TEMP_RANGE_C = (-90.0, 60.0)
HUMIDITY_RANGE_PCT = (0.0, 100.0)
PRESSURE_RANGE_HPA = (850.0, 1085.0)


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    passed: bool
    severity: str  # "info" | "warning" | "critical"
    details: dict = field(default_factory=dict)


def check_freshness(
    latest_observation_time: datetime | None, now: datetime, max_staleness_minutes: float
) -> CheckResult:
    """Flags a location whose most recent observation is older than
    `max_staleness_minutes` — the direct signal that ingestion has silently
    stopped working for that location (API errors, quota exhaustion, a
    crashed DAG) well before someone notices missing data downstream.
    """
    if latest_observation_time is None:
        return CheckResult("freshness", False, "critical", {"reason": "no observations found"})

    staleness_minutes = (now - latest_observation_time).total_seconds() / 60
    passed = staleness_minutes <= max_staleness_minutes
    if passed:
        severity = "info"
    elif staleness_minutes <= max_staleness_minutes * 3:
        severity = "warning"
    else:
        severity = "critical"
    return CheckResult(
        "freshness",
        passed,
        severity,
        {
            "staleness_minutes": round(staleness_minutes, 1),
            "threshold_minutes": max_staleness_minutes,
        },
    )


def check_value_ranges(
    temperature_c: float | None, humidity_pct: float | None, pressure_hpa: float | None
) -> CheckResult:
    problems = []
    if temperature_c is not None and not (TEMP_RANGE_C[0] <= temperature_c <= TEMP_RANGE_C[1]):
        problems.append(f"temperature_c={temperature_c} outside {TEMP_RANGE_C}")
    if humidity_pct is not None and not (
        HUMIDITY_RANGE_PCT[0] <= humidity_pct <= HUMIDITY_RANGE_PCT[1]
    ):
        problems.append(f"humidity_pct={humidity_pct} outside {HUMIDITY_RANGE_PCT}")
    if pressure_hpa is not None and not (
        PRESSURE_RANGE_HPA[0] <= pressure_hpa <= PRESSURE_RANGE_HPA[1]
    ):
        problems.append(f"pressure_hpa={pressure_hpa} outside {PRESSURE_RANGE_HPA}")

    passed = not problems
    return CheckResult(
        "value_ranges", passed, "info" if passed else "critical", {"problems": problems}
    )


def check_required_fields(
    temperature_c: float | None, humidity_pct: float | None, pressure_hpa: float | None
) -> CheckResult:
    """Missing core fields degrade feature quality without being outright
    wrong, so this is a warning, not critical — unlike an out-of-range value,
    which is always a hard error.
    """
    missing = [
        name
        for name, value in (
            ("temperature_c", temperature_c),
            ("humidity_pct", humidity_pct),
            ("pressure_hpa", pressure_hpa),
        )
        if value is None
    ]
    passed = not missing
    return CheckResult(
        "required_fields", passed, "info" if passed else "warning", {"missing": missing}
    )
