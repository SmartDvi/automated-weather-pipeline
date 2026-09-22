import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

import mlflow

from weatherml.config import get_settings
from weatherml.ml import registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedModel:
    model: object
    version: str
    loaded_at: datetime


class ModelCache:
    """Holds the current @production model per horizon in memory, refreshed
    on a background timer rather than per-request — /predict latency should
    never include an MLflow round-trip. `refresh()` only swaps the in-memory
    model when the resolved production *version* actually changed, so a
    request in flight never observes a half-swapped model and idle refreshes
    are cheap (one registry lookup, no model download) when nothing changed.
    """

    def __init__(self, horizons: tuple[int, ...] = (1, 3)):
        self.horizons = horizons
        self._models: dict[int, LoadedModel | None] = dict.fromkeys(horizons)
        self._lock = threading.Lock()

    def get(self, horizon_hours: int) -> LoadedModel | None:
        with self._lock:
            return self._models.get(horizon_hours)

    def refresh(self) -> None:
        settings = get_settings()
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        client = registry.get_client()

        for horizon in self.horizons:
            model_name = registry.registered_model_name(horizon)
            try:
                version_info = client.get_model_version_by_alias(
                    model_name, registry.ALIAS_PRODUCTION
                )
            except Exception:
                continue  # no production model registered yet for this horizon

            current = self._models.get(horizon)
            if current is not None and current.version == version_info.version:
                continue  # unchanged — skip the model download entirely

            try:
                model = mlflow.pyfunc.load_model(
                    f"models:/{model_name}@{registry.ALIAS_PRODUCTION}"
                )
            except Exception:
                logger.exception("model_reload_failed", extra={"model_name": model_name})
                continue

            with self._lock:
                self._models[horizon] = LoadedModel(
                    model=model, version=version_info.version, loaded_at=datetime.now(UTC)
                )
            logger.info(
                "model_loaded", extra={"model_name": model_name, "version": version_info.version}
            )

    async def refresh_loop(self, interval_seconds: int) -> None:
        while True:
            await asyncio.to_thread(self.refresh)
            await asyncio.sleep(interval_seconds)


# Module-level singleton — imported directly by main.py (to start the
# refresh loop) and by the predictions router (to serve from it). Simpler
# than threading it through app.state for a single-process service.
model_cache = ModelCache()
