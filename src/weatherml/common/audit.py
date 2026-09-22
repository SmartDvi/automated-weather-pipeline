import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from weatherml.db.models import PipelineRun

logger = logging.getLogger(__name__)


@contextmanager
def track_run(
    session: Session, *, dag_id: str, task_id: str, dag_run_id: str | None = None
) -> Iterator[PipelineRun]:
    """Wrap a DAG task body. Opens a `running` ops.pipeline_runs row immediately
    (on the same session/transaction as the task's other inserts, so those
    inserts have a valid run_id FK to reference before anything commits), then
    marks it `success` or `failed` based on whether the block raised.

    Usage:
        with session_scope() as session, track_run(session, dag_id=..., task_id=...) as run:
            ... do work, referencing run.run_id as ingestion_run_id ...
    """
    run = PipelineRun(dag_id=dag_id, task_id=task_id, dag_run_id=dag_run_id, status="running")
    session.add(run)
    session.flush()  # assigns run.run_id without committing the outer transaction
    try:
        yield run
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        logger.exception("pipeline_run_failed", extra={"dag_id": dag_id, "task_id": task_id})
        raise
    else:
        # A caller may have already set a terminal status (e.g. a caught,
        # handled failure it wants recorded without re-raising, which would
        # otherwise roll back everything committed in this block including
        # this row). Only default to "success" if nothing did.
        if run.status == "running":
            run.status = "success"
            run.finished_at = datetime.now(UTC)
