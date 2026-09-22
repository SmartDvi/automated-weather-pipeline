from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from weatherml.config import get_settings
from weatherml.db import models  # noqa: F401  (imported so Base.metadata is fully populated)
from weatherml.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Single source of truth for the DB URL: weatherml.config.Settings (.env),
# not a duplicated value in alembic.ini.
config.set_main_option("sqlalchemy.url", str(get_settings().database_url))

target_metadata = Base.metadata

SCHEMAS = ("raw", "core", "features", "ops")


def include_object(object, name, type_, reflected, compare_to):
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="ops",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        for schema in SCHEMAS:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="ops",
            include_schemas=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
