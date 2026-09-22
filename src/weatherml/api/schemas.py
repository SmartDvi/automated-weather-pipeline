from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: int
    location_key: str
    display_name: str
    country_code: str
    latitude: float | None
    longitude: float | None
    timezone: str


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_time: datetime
    temperature_c: float | None
    feelslike_c: float | None
    humidity_pct: int | None
    pressure_hpa: float | None
    wind_speed_kph: float | None
    precip_mm: float | None
    weather_description: str | None
    is_day: bool | None


class PredictRequest(BaseModel):
    location_id: int
    horizon_hours: int = 1


class PredictResponse(BaseModel):
    location_id: int
    horizon_hours: int
    predicted_temp_c: float
    model_name: str
    model_version: str
    model_alias: str
    predicted_at: datetime
    based_on_observation_time: datetime | None
