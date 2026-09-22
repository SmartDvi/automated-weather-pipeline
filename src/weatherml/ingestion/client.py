import logging
import random
import time

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from weatherml.ingestion.schemas import (
    RETRYABLE_ERROR_CODES,
    WeatherstackErrorDetail,
    WeatherstackSuccessResponse,
    parse_response,
)

logger = logging.getLogger(__name__)


class WeatherstackError(Exception):
    def __init__(self, detail: WeatherstackErrorDetail):
        self.detail = detail
        super().__init__(f"weatherstack error {detail.code} ({detail.type}): {detail.info}")


class WeatherstackQuotaExceededError(WeatherstackError):
    """Rate-limit / usage-window error. Retried with backoff — the window may
    reset within the retry budget — before being surfaced to the caller.
    """


class WeatherstackClientError(WeatherstackError):
    """Bad access key, bad query, disallowed function, etc. Never retried:
    retrying a request that's wrong by construction just burns time and, for
    key/plan errors, real API quota.
    """


_RETRYABLE_EXCEPTIONS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.HTTPError,
    WeatherstackQuotaExceededError,
)


class WeatherstackClient:
    def __init__(self, base_url: str, access_key: str, timeout_seconds: int = 10):
        self._base_url = base_url
        self._access_key = access_key
        self._timeout_seconds = timeout_seconds
        self._session = requests.Session()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )
    def get_current(self, query: str) -> WeatherstackSuccessResponse:
        """Fetch current conditions for `query` (a "lat,lon" pair for our
        seeded locations — see migrations/versions/0002 for why lat/lon
        rather than a city name string).

        Raises WeatherstackQuotaExceededError (after retrying) or
        WeatherstackClientError (immediately, no retry) on failure.
        """
        response = self._session.get(
            self._base_url,
            params={"access_key": self._access_key, "query": query, "units": "m"},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        parsed = parse_response(response.json())

        if isinstance(parsed, WeatherstackSuccessResponse):
            return parsed

        detail = parsed.error
        if detail.code in RETRYABLE_ERROR_CODES:
            logger.warning(
                "weatherstack_retryable_error",
                extra={"query": query, "error_code": detail.code, "error_type": detail.type},
            )
            raise WeatherstackQuotaExceededError(detail)

        logger.error(
            "weatherstack_client_error",
            extra={"query": query, "error_code": detail.code, "error_type": detail.type},
        )
        raise WeatherstackClientError(detail)


class MockWeatherstackClient:
    """Stand-in used when Settings.use_mock_client is true (default posture
    for local dev / CI). Generates plausible, gently time-varying synthetic
    readings entirely in-process — no fixture file dependency — so it works
    identically from a source checkout or a built container image, and never
    touches real API quota. Same interface as WeatherstackClient.
    """

    def get_current(self, query: str) -> WeatherstackSuccessResponse:
        lat_str, _, lon_str = query.partition(",")
        rng = random.Random(f"{query}-{int(time.time() // 300)}")  # stable within a 5-min slot
        base_temp = 15.0 - abs(float(lat_str or 0)) * 0.3  # crude latitude-vs-temperature gradient
        payload = {
            "location": {
                "name": query,
                "country": "Mock",
                "lat": lat_str or "0",
                "lon": lon_str or "0",
                "timezone_id": "UTC",
                "localtime_epoch": int(time.time()),
                "utc_offset": "0.0",
            },
            "current": {
                "observation_time": "00:00 AM",
                "temperature": round(base_temp + rng.uniform(-4, 4), 1),
                "weather_code": 113,
                "weather_descriptions": ["Sunny"],
                "astro": {
                    "sunrise": "06:00 AM",
                    "sunset": "06:00 PM",
                    "moon_phase": "New Moon",
                    "moon_illumination": 10,
                },
                "air_quality": {
                    "co": str(round(rng.uniform(150, 400), 1)),
                    "no2": str(round(rng.uniform(5, 40), 1)),
                    "o3": str(round(rng.uniform(20, 80), 1)),
                    "so2": str(round(rng.uniform(1, 20), 1)),
                    "pm2_5": str(round(rng.uniform(2, 35), 1)),
                    "pm10": str(round(rng.uniform(5, 50), 1)),
                    "us-epa-index": str(rng.randint(1, 4)),
                    "gb-defra-index": str(rng.randint(1, 6)),
                },
                "wind_speed": round(rng.uniform(0, 40), 1),
                "wind_degree": rng.randint(0, 359),
                "wind_dir": "N",
                "pressure": round(1013 + rng.uniform(-15, 15), 1),
                "precip": round(max(0, rng.uniform(-2, 3)), 1),
                "humidity": rng.randint(30, 95),
                "cloudcover": rng.randint(0, 100),
                "feelslike": round(base_temp + rng.uniform(-5, 5), 1),
                "uv_index": rng.randint(0, 10),
                "visibility": round(rng.uniform(2, 10), 1),
                "is_day": "yes",
            },
        }
        return WeatherstackSuccessResponse.model_validate(payload)
