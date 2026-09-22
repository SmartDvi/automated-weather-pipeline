from functools import lru_cache

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central runtime configuration, loaded from environment / .env.

    Every module that needs config imports `get_settings()` rather than
    reading `os.environ` directly, so there is exactly one place that knows
    where secrets and tunables come from.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Weatherstack
    weatherstack_api_key: SecretStr
    weatherstack_base_url: str = "http://api.weatherstack.com/current"
    use_mock_client: bool = False

    # Database
    database_url: PostgresDsn

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_artifact_root: str = "/mlflow/artifacts"

    # Pipeline behavior
    ingestion_poll_interval_minutes: int = 5
    request_timeout_seconds: int = 10
    feature_lookback_hours: int = 24
    model_refresh_interval_seconds: int = 600
    improvement_threshold: float = 0.02
    log_level: str = "INFO"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Dashboard (talks to the API above over HTTP, never to weatherstack or
    # Postgres directly — refreshing it doesn't touch API quota)
    dashboard_api_base_url: str = "http://localhost:8811"
    dashboard_port: int = 8050
    dashboard_refresh_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
