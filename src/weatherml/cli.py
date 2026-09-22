"""Subprocess entrypoint used by Airflow's BashOperator tasks.

Why a CLI boundary instead of pip-installing weatherml into Airflow's own
Python environment: Airflow 2.x pins SQLAlchemy to <2.0, while weatherml's
ORM models use the SQLAlchemy 2.0 `Mapped`/`mapped_column` API (and pulls in
mlflow/xgboost/pandas, which churn quickly and would fight Airflow's own
dependency constraints). Rather than downgrading our ORM or fighting
constraint files, weatherml is installed into a *separate* venv
(/opt/weatherml-venv, built in docker/airflow/Dockerfile) baked into the same
Airflow image, and every DAG task shells out to
`/opt/weatherml-venv/bin/python -m weatherml.cli <subcommand>`. Airflow's own
environment never imports weatherml, so it stays fully vanilla and upgrading
Airflow later touches nothing here. Each subcommand exits 0 on success /
non-zero on failure, which is BashOperator's success signal, and prints only
its designed output to stdout (JSON where noted) so it can be captured as an
Airflow XCom.
"""

import argparse
import json
import logging
import sys

from weatherml.config import get_settings
from weatherml.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _cmd_locations_list_active(_args: argparse.Namespace) -> int:
    from weatherml.db.models import Location
    from weatherml.db.session import session_scope

    with session_scope() as session:
        rows = session.query(Location).filter(Location.is_active.is_(True)).all()
        payload = [
            {
                "location_id": r.location_id,
                "location_key": r.location_key,
                "display_name": r.display_name,
            }
            for r in rows
        ]
    print(json.dumps(payload))
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from weatherml.ingestion.service import ingest_location

    ok = ingest_location(location_id=args.location_id, dag_run_id=args.dag_run_id)
    return 0 if ok else 1


def _cmd_features_build(args: argparse.Namespace) -> int:
    from weatherml.features.pipeline import build_and_store_features

    build_and_store_features(location_id=args.location_id, dag_run_id=args.dag_run_id)
    return 0


def _cmd_train_run(args: argparse.Namespace) -> int:
    from weatherml.ml.train import run_training_cycle

    run_training_cycle(dag_run_id=args.dag_run_id)
    return 0


def _cmd_quality_check(args: argparse.Namespace) -> int:
    from weatherml.quality.service import run_all_checks

    all_passed = run_all_checks(dag_run_id=args.dag_run_id)
    return 0 if all_passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weatherml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("locations-list-active")
    p.set_defaults(func=_cmd_locations_list_active)

    p = sub.add_parser("ingest")
    p.add_argument("--location-id", type=int, required=True)
    p.add_argument("--dag-run-id", type=str, default=None)
    p.set_defaults(func=_cmd_ingest)

    p = sub.add_parser("features-build")
    p.add_argument("--location-id", type=int, required=True)
    p.add_argument("--dag-run-id", type=str, default=None)
    p.set_defaults(func=_cmd_features_build)

    p = sub.add_parser("train-run")
    p.add_argument("--dag-run-id", type=str, default=None)
    p.set_defaults(func=_cmd_train_run)

    p = sub.add_parser("quality-check")
    p.add_argument("--dag-run-id", type=str, default=None)
    p.set_defaults(func=_cmd_quality_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception:
        logger.exception("cli_command_failed", extra={"command": args.command})
        return 1


if __name__ == "__main__":
    sys.exit(main())
