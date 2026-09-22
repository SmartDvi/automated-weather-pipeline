import logging
from dataclasses import dataclass

import mlflow
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from weatherml.config import get_settings

logger = logging.getLogger(__name__)

ALIAS_PRODUCTION = "production"
ALIAS_STAGING = "staging"


def registered_model_name(horizon_hours: int) -> str:
    # Two separate registered models (1h/3h), not one model with a "horizon"
    # param, because they're genuinely different prediction tasks with
    # independent quality bars and promotion timelines.
    return f"weather_temp_forecast_{horizon_hours}h"


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reason: str


def decide_promotion(
    candidate_mae: float,
    baseline_mae: float,
    production_mae: float | None,
    improvement_threshold: float = 0.02,
) -> PromotionDecision:
    """Pure function, no MLflow calls — fully unit-testable on plain floats.

    1. The candidate must beat the naive persistence baseline outright; a
       model that can't clear that bar is broken, not just mediocre.
    2. No production model yet -> promote unconditionally once rule 1 holds
       (bootstrap case).
    3. Otherwise promote only if the candidate beats current production by
       at least `improvement_threshold` (relative MAE), so the production
       alias doesn't churn on run-to-run noise.
    """
    if candidate_mae >= baseline_mae:
        return PromotionDecision(
            False,
            f"candidate MAE {candidate_mae:.3f} does not beat baseline MAE {baseline_mae:.3f}",
        )

    if production_mae is None:
        return PromotionDecision(True, "no current production model — bootstrap promotion")

    required_mae = production_mae * (1 - improvement_threshold)
    if candidate_mae <= required_mae:
        return PromotionDecision(
            True,
            f"candidate MAE {candidate_mae:.3f} beats production MAE {production_mae:.3f} "
            f"by >= {improvement_threshold:.0%}",
        )

    return PromotionDecision(
        False,
        f"candidate MAE {candidate_mae:.3f} does not sufficiently beat production MAE "
        f"{production_mae:.3f} (required <= {required_mae:.3f})",
    )


def get_client() -> MlflowClient:
    settings = get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    return MlflowClient(tracking_uri=settings.mlflow_tracking_uri)


def get_production_model_version(client: MlflowClient, model_name: str):
    try:
        return client.get_model_version_by_alias(model_name, ALIAS_PRODUCTION)
    except MlflowException:
        return None


def ensure_registered_model(client: MlflowClient, model_name: str) -> None:
    try:
        client.get_registered_model(model_name)
    except MlflowException:
        client.create_registered_model(model_name)


def promote(client: MlflowClient, model_name: str, version: str) -> None:
    client.set_registered_model_alias(model_name, ALIAS_STAGING, version)
    client.set_registered_model_alias(model_name, ALIAS_PRODUCTION, version)
    logger.info("model_promoted", extra={"model_name": model_name, "version": version})


def load_production_model(horizon_hours: int):
    settings = get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    model_name = registered_model_name(horizon_hours)
    return mlflow.pyfunc.load_model(f"models:/{model_name}@{ALIAS_PRODUCTION}")
