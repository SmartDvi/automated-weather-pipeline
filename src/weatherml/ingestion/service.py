import logging
from datetime import UTC, datetime, time

from weatherml.common.audit import track_run
from weatherml.common.time import epoch_and_offset_to_utc
from weatherml.config import get_settings
from weatherml.db.session import session_scope
from weatherml.ingestion.client import (
    MockWeatherstackClient,
    WeatherstackClient,
    WeatherstackError,
)
from weatherml.ingestion.repository import get_location, insert_raw, upsert_observation
from weatherml.ingestion.schemas import WeatherstackSuccessResponse

logger = logging.getLogger(__name__)


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%I:%M %p").time()
    except ValueError:
        return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    as_float = _to_float(value)
    return int(as_float) if as_float is not None else None


def _map_to_observation_fields(resp: WeatherstackSuccessResponse) -> tuple[datetime, dict]:
    current = resp.current
    location = resp.location
    astro = current.astro
    aq = current.air_quality

    observation_time = epoch_and_offset_to_utc(location.localtime_epoch, float(location.utc_offset))

    fields = {
        "temperature_c": current.temperature,
        "feelslike_c": current.feelslike,
        "humidity_pct": current.humidity,
        "pressure_hpa": current.pressure,
        "wind_speed_kph": current.wind_speed,
        "wind_degree": current.wind_degree,
        "wind_dir": current.wind_dir,
        "precip_mm": current.precip,
        "cloudcover_pct": current.cloudcover,
        "uv_index": current.uv_index,
        "visibility_km": current.visibility,
        "weather_code": current.weather_code,
        "weather_description": current.weather_descriptions[0]
        if current.weather_descriptions
        else None,
        "is_day": current.is_day == "yes",
        "sunrise": _parse_time(astro.sunrise) if astro else None,
        "sunset": _parse_time(astro.sunset) if astro else None,
        "moon_phase": astro.moon_phase if astro else None,
        "moon_illumination_pct": astro.moon_illumination if astro else None,
        "aqi_co": _to_float(aq.co) if aq else None,
        "aqi_no2": _to_float(aq.no2) if aq else None,
        "aqi_o3": _to_float(aq.o3) if aq else None,
        "aqi_so2": _to_float(aq.so2) if aq else None,
        "aqi_pm2_5": _to_float(aq.pm2_5) if aq else None,
        "aqi_pm10": _to_float(aq.pm10) if aq else None,
        "aqi_us_epa_index": _to_int(aq.us_epa_index) if aq else None,
        "aqi_gb_defra_index": _to_int(aq.gb_defra_index) if aq else None,
    }
    return observation_time, fields


def ingest_location(location_id: int, dag_run_id: str | None = None) -> bool:
    """Fetch + persist the latest reading for one location. Returns True on
    success, False on failure (including after retries are exhausted) —
    the CLI maps this to a process exit code so a BashOperator mapped task
    instance fails for just that location, leaving siblings unaffected.
    """
    settings = get_settings()

    with (
        session_scope() as session,
        track_run(
            session,
            dag_id="ingest_weather",
            task_id=f"ingest_location_{location_id}",
            dag_run_id=dag_run_id,
        ) as run,
    ):
        location = get_location(session, location_id)
        if location is None:
            raise ValueError(f"location_id={location_id} not found or inactive")

        client = (
            MockWeatherstackClient()
            if settings.use_mock_client
            else WeatherstackClient(
                base_url=settings.weatherstack_base_url,
                access_key=settings.weatherstack_api_key.get_secret_value(),
                timeout_seconds=settings.request_timeout_seconds,
            )
        )
        query = f"{location.latitude},{location.longitude}"

        try:
            response = client.get_current(query)
        except WeatherstackError as exc:
            # Commit the audit trail (raw error row + failed pipeline_run)
            # even though the operation failed — DO NOT re-raise here, since
            # session_scope() would roll back this very row along with it.
            # Failure is signaled by the False return -> non-zero CLI exit
            # code -> BashOperator task failure, which Airflow retries and
            # alerts on independent of this commit.
            insert_raw(
                session,
                location_id=location_id,
                ingestion_run_id=run.run_id,
                http_status=200,
                is_error=True,
                error_code=exc.detail.code,
                error_info=exc.detail.info,
                payload={"error": exc.detail.model_dump()},
            )
            run.rows_processed = 0
            run.status = "failed"
            run.error_message = f"{exc.detail.code} {exc.detail.type}: {exc.detail.info}"[:2000]
            run.finished_at = datetime.now(UTC)
            logger.error(
                "ingestion_failed",
                extra={"location_id": location_id, "error_code": exc.detail.code},
            )
            return False

        raw = insert_raw(
            session,
            location_id=location_id,
            ingestion_run_id=run.run_id,
            http_status=200,
            is_error=False,
            error_code=None,
            error_info=None,
            payload=response.model_dump(by_alias=True),
        )

        observation_time, fields = _map_to_observation_fields(response)
        upsert_observation(
            session,
            location_id=location_id,
            observation_time=observation_time,
            fields=fields,
            raw_observation_id=raw.id,
            ingestion_run_id=run.run_id,
        )
        run.rows_processed = 1
        logger.info(
            "ingestion_succeeded",
            extra={"location_id": location_id, "observation_time": str(observation_time)},
        )
        return True
