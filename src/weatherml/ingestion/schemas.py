"""Typed models for weatherstack's two response shapes.

weatherstack returns HTTP 200 for BOTH success and failure — failures carry a
top-level `error` object instead of `location`/`current`. `parse_response`
is the single place that looks at the raw dict and decides which shape it is,
so nothing downstream ever touches untyped JSON.
"""

from typing import Literal

from pydantic import BaseModel, Field


class WeatherstackAstro(BaseModel):
    sunrise: str | None = None
    sunset: str | None = None
    moon_phase: str | None = None
    moon_illumination: int | None = None


class WeatherstackAirQuality(BaseModel):
    co: str | None = None
    no2: str | None = None
    o3: str | None = None
    so2: str | None = None
    pm2_5: str | None = None
    pm10: str | None = None
    us_epa_index: str | None = Field(default=None, alias="us-epa-index")
    gb_defra_index: str | None = Field(default=None, alias="gb-defra-index")

    model_config = {"populate_by_name": True}


class WeatherstackCurrent(BaseModel):
    observation_time: str | None = None
    temperature: float | None = None
    weather_code: int | None = None
    weather_descriptions: list[str] = Field(default_factory=list)
    astro: WeatherstackAstro | None = None
    air_quality: WeatherstackAirQuality | None = None
    wind_speed: float | None = None
    wind_degree: int | None = None
    wind_dir: str | None = None
    pressure: float | None = None
    precip: float | None = None
    humidity: int | None = None
    cloudcover: int | None = None
    feelslike: float | None = None
    uv_index: int | None = None
    visibility: float | None = None
    is_day: str | None = None


class WeatherstackLocation(BaseModel):
    name: str
    country: str
    lat: str
    lon: str
    timezone_id: str
    localtime_epoch: int
    utc_offset: str


class WeatherstackSuccessResponse(BaseModel):
    success: Literal[True] = True
    location: WeatherstackLocation
    current: WeatherstackCurrent


class WeatherstackErrorDetail(BaseModel):
    code: int
    type: str
    info: str


class WeatherstackErrorResponse(BaseModel):
    success: Literal[False] = False
    error: WeatherstackErrorDetail


# Error codes that plausibly reflect a transient condition worth retrying
# with backoff (rate limits / usage windows). Everything else (bad key, bad
# query, function not permitted, ...) is a client-side error that retrying
# cannot fix and should fail fast to avoid wasting quota and time.
RETRYABLE_ERROR_CODES = {104, 105}


def parse_response(payload: dict) -> WeatherstackSuccessResponse | WeatherstackErrorResponse:
    if "error" in payload or payload.get("success") is False:
        return WeatherstackErrorResponse.model_validate(payload)
    return WeatherstackSuccessResponse.model_validate(payload)
