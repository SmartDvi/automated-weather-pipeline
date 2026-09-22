import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from weatherml.api.model_loader import model_cache
from weatherml.api.routers import health, locations, observations, predictions
from weatherml.config import get_settings
from weatherml.logging_config import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    # Synchronous initial load so the very first requests aren't served
    # against an empty cache while waiting for the first background tick.
    model_cache.refresh()
    refresh_task = asyncio.create_task(
        model_cache.refresh_loop(get_settings().model_refresh_interval_seconds)
    )
    yield
    refresh_task.cancel()


app = FastAPI(title="WeatherML API", version="0.1.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)

app.include_router(health.router)
app.include_router(locations.router)
app.include_router(observations.router)
app.include_router(predictions.router)
