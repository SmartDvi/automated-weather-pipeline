# Airflow's own environment stays 100% stock (apache/airflow:2.10.x pins
# SQLAlchemy <2.0; weatherml's ORM needs 2.0's Mapped/mapped_column API, and
# pulls in mlflow/xgboost/pandas which would otherwise fight Airflow's
# constraint file). weatherml is installed into a SEPARATE venv that DAG
# tasks invoke via BashOperator + `weatherml/cli.py` — see cli.py's docstring.
#
# That venv is built from uv.lock (not a fresh pip resolve of pyproject.toml)
# so every build gets the exact package versions developed/tested against
# locally, not "whatever's newest on PyPI on build day."
FROM apache/airflow:2.10.5-python3.12

USER root

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/weatherml-venv

COPY --chown=root:root pyproject.toml uv.lock /opt/weatherml-src/
COPY --chown=root:root src /opt/weatherml-src/src

RUN cd /opt/weatherml-src && uv sync --frozen --extra ml --no-dev

USER airflow
