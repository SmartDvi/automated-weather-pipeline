from datetime import UTC, datetime

from sqlalchemy import select

from weatherml.common.audit import track_run
from weatherml.config import get_settings
from weatherml.db.models import DataQualityCheck, Location, WeatherObservation
from weatherml.db.session import session_scope
from weatherml.quality import checks as c
from weatherml.quality.alerting import AlertEvent, notify

# A location is flagged stale once its latest reading is older than this
# multiple of the ingestion interval — 3x gives ingestion room for a couple
# of missed/retried cycles before crying wolf.
STALENESS_MULTIPLIER = 3


def _latest_observation(session, location_id: int) -> WeatherObservation | None:
    stmt = (
        select(WeatherObservation)
        .where(WeatherObservation.location_id == location_id)
        .order_by(WeatherObservation.observation_time.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def run_all_checks(dag_run_id: str | None = None) -> bool:
    """Runs freshness/range/completeness checks for every active location,
    logs every result to ops.data_quality_checks (not just failures — a
    clean history of passes is what lets you later ask "when did this start
    failing"), and fires the alert hook on any critical failure. Returns
    False if anything failed, which the CLI maps to a non-zero exit so
    Airflow surfaces it.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    max_staleness_minutes = settings.ingestion_poll_interval_minutes * STALENESS_MULTIPLIER
    all_passed = True

    with (
        session_scope() as session,
        track_run(
            session,
            dag_id="data_quality_monitoring",
            task_id="run_all_checks",
            dag_run_id=dag_run_id,
        ) as run,
    ):
        locations = list(session.scalars(select(Location).where(Location.is_active.is_(True))))
        checks_run = 0

        for location in locations:
            obs = _latest_observation(session, location.location_id)
            results = [
                c.check_freshness(obs.observation_time if obs else None, now, max_staleness_minutes)
            ]
            if obs is not None:
                results.append(
                    c.check_value_ranges(
                        float(obs.temperature_c) if obs.temperature_c is not None else None,
                        float(obs.humidity_pct) if obs.humidity_pct is not None else None,
                        float(obs.pressure_hpa) if obs.pressure_hpa is not None else None,
                    )
                )
                results.append(
                    c.check_required_fields(obs.temperature_c, obs.humidity_pct, obs.pressure_hpa)
                )

            for result in results:
                session.add(
                    DataQualityCheck(
                        run_id=run.run_id,
                        check_name=result.check_name,
                        location_id=location.location_id,
                        severity=result.severity,
                        passed=result.passed,
                        details=result.details,
                    )
                )
                checks_run += 1
                if not result.passed:
                    all_passed = False
                    if result.severity == "critical":
                        notify(
                            AlertEvent(
                                check_name=result.check_name,
                                location_key=location.location_key,
                                severity=result.severity,
                                details=result.details,
                            )
                        )

        run.rows_processed = checks_run

    return all_passed
