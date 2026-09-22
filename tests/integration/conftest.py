"""Integration tests run against a real, ephemeral Postgres (via
testcontainers) rather than the docker-compose `postgres` service —
hermetic, parallel-safe, and works in CI without the full compose stack
running. Migrated once per test session with the real Alembic migrations
(the same ones that run in production), so these tests exercise the actual
schema, not a hand-rolled approximation of it.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

PROJECT_ROOT = Path(__file__).parents[2]

# Tables truncated between tests, in FK-safe order (children before parents).
# ops.pipeline_runs is truncated last since raw/core/features/ops.* all
# reference it.
_TRUNCATE_ORDER = [
    "ops.model_predictions",
    "ops.data_quality_checks",
    "features.weather_features",
    "core.weather_observations",
    "raw.weather_observations_raw",
    "ops.pipeline_runs",
]


@pytest.fixture(scope="session")
def database_url() -> str:
    with PostgresContainer("postgres:16", driver="psycopg2") as container:
        url = container.get_connection_url()

        os.environ["DATABASE_URL"] = url
        from weatherml.config import get_settings

        get_settings.cache_clear()

        alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        command.upgrade(alembic_cfg, "head")

        yield url


@pytest.fixture()
def db_session(database_url):
    from weatherml.db.session import get_engine, get_sessionmaker

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    engine = get_engine()
    with engine.begin() as conn:
        for table in _TRUNCATE_ORDER:
            conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))

    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
