import logging
from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.pyfunc
import mlflow.sklearn
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from xgboost import XGBRegressor

from weatherml.common.audit import track_run
from weatherml.config import get_settings
from weatherml.db.session import session_scope
from weatherml.ml import registry
from weatherml.ml.baseline import PersistenceModel
from weatherml.ml.dataset import FEATURE_COLUMNS, load_training_frame, time_ordered_split
from weatherml.ml.evaluate import evaluate_predictions

logger = logging.getLogger(__name__)

# mlflow's sklearn flavor serializes via skops, which audits pickled types
# and refuses anything outside sklearn's own core classes by default —
# numpy.dtype shows up in virtually every sklearn model's internal state,
# and our primary candidate also carries genuine xgboost types. We trust
# them because we trained these models ourselves in this run; this isn't
# deserializing a third-party artifact.
SKOPS_TRUSTED_TYPES = ["numpy.dtype", "xgboost.core.Booster", "xgboost.sklearn.XGBRegressor"]

EXPERIMENT_NAME = "weather_temp_forecast"
HORIZONS_HOURS = (1, 3)
# ~16h+ of 5-min data across all active locations. Below this, skip training
# rather than fit (and possibly promote) a model with no real signal — an
# honest "not enough data yet" is better than a garbage model in production.
MIN_TRAINING_ROWS = 200


def _prepare_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    X = df[FEATURE_COLUMNS].copy()
    y = df["target_temp_c"].astype(float)
    return X, y


def _make_imputer() -> SimpleImputer:
    # keep_empty_features=True: an all-NaN column (e.g. heat_index_c outside
    # a heatwave) must still come out as a column, not silently disappear —
    # otherwise the model's input width drifts between training runs based
    # on what happened to be present, breaking the fixed input schema serving
    # depends on and desyncing FEATURE_COLUMNS from the model's actual inputs.
    return SimpleImputer(strategy="median", keep_empty_features=True)


def _fit_candidate(X_train: pd.DataFrame, y_train: pd.Series) -> Pipeline:
    pipeline = Pipeline(
        [
            ("imputer", _make_imputer()),
            (
                "model",
                XGBRegressor(
                    n_estimators=200,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    random_state=42,
                ),
            ),
        ]
    )
    pipeline.fit(X_train, y_train)
    return pipeline


def _fit_secondary(X_train: pd.DataFrame, y_train: pd.Series) -> Pipeline:
    pipeline = Pipeline([("imputer", _make_imputer()), ("model", Ridge(alpha=1.0))])
    pipeline.fit(X_train, y_train)
    return pipeline


def _log_feature_importance(pipeline: Pipeline, feature_names: list[str]) -> None:
    model = pipeline.named_steps["model"]
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return

    importance_df = pd.DataFrame({"feature": feature_names, "importance": importances}).sort_values(
        "importance", ascending=False
    )
    mlflow.log_table(importance_df, artifact_file="feature_importance.json")

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(importance_df["feature"], importance_df["importance"])
    ax.invert_yaxis()
    ax.set_xlabel("importance")
    fig.tight_layout()
    mlflow.log_figure(fig, "feature_importance.png")
    plt.close(fig)


def train_for_horizon(horizon_hours: int, dag_run_id: str | None) -> dict:
    """Trains, evaluates, and (if it clears the promotion bar) registers a
    model for one horizon. Returns a JSON-able summary recorded into
    ops.pipeline_runs.extra by run_training_cycle.
    """
    settings = get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    with session_scope() as session:
        df = load_training_frame(session, horizon_hours)

    if len(df) < MIN_TRAINING_ROWS:
        logger.info(
            "insufficient_training_data",
            extra={"horizon_hours": horizon_hours, "rows": len(df), "required": MIN_TRAINING_ROWS},
        )
        return {"horizon_hours": horizon_hours, "skipped": True, "rows": len(df)}

    train_df, test_df = time_ordered_split(df, test_size=0.2)
    X_train, y_train = _prepare_xy(train_df)
    X_test, y_test = _prepare_xy(test_df)

    run_name = f"xgboost_{horizon_hours}h_{datetime.now(UTC):%Y%m%d_%H%M%S}"
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags(
            {
                "horizon_hours": str(horizon_hours),
                "dag_run_id": dag_run_id or "manual",
                "feature_set_version": "1",
                "n_locations": str(df["location_id"].nunique()),
            }
        )
        mlflow.log_params(
            {
                "model_type": "xgboost",
                "n_estimators": 200,
                "max_depth": 4,
                "learning_rate": 0.05,
                "train_start": str(train_df["feature_time"].min()),
                "train_end": str(train_df["feature_time"].max()),
                "test_start": str(test_df["feature_time"].min()),
                "test_end": str(test_df["feature_time"].max()),
                "n_train": len(train_df),
                "n_test": len(test_df),
            }
        )

        # --- baseline: logged every cycle so every candidate has an
        # always-present naive-forecast comparison, side by side in metrics ---
        baseline_metrics = evaluate_predictions(
            y_test, PersistenceModel().predict(None, test_df[["current_temp_c"]])
        )
        mlflow.log_metrics({f"{k}_baseline": v for k, v in baseline_metrics.items()})
        mlflow.pyfunc.log_model(python_model=PersistenceModel(), name="baseline")

        # --- primary candidate ---
        candidate = _fit_candidate(X_train, y_train)
        candidate_metrics = evaluate_predictions(y_test, candidate.predict(X_test))
        mlflow.log_metrics(candidate_metrics)
        _log_feature_importance(candidate, FEATURE_COLUMNS)

        signature = mlflow.models.infer_signature(X_train, candidate.predict(X_train))
        mlflow.sklearn.log_model(
            candidate,
            name="model",
            signature=signature,
            input_example=X_train.head(3),
            skops_trusted_types=SKOPS_TRUSTED_TYPES,
        )

        # --- secondary comparison model (logged for visibility, never
        # eligible for promotion — only the primary candidate is) ---
        secondary = _fit_secondary(X_train, y_train)
        secondary_metrics = evaluate_predictions(y_test, secondary.predict(X_test))
        mlflow.log_metrics({f"{k}_ridge": v for k, v in secondary_metrics.items()})
        mlflow.sklearn.log_model(
            secondary,
            name="model_ridge",
            input_example=X_train.head(3),
            skops_trusted_types=SKOPS_TRUSTED_TYPES,
        )

        # --- promotion decision: re-evaluate current production (if any) on
        # THIS run's held-out split, an apples-to-apples comparison rather
        # than trusting its historically-logged metric from a different split ---
        model_name = registry.registered_model_name(horizon_hours)
        client = registry.get_client()
        registry.ensure_registered_model(client, model_name)
        production_version = registry.get_production_model_version(client, model_name)
        production_mae = None
        if production_version is not None:
            try:
                production_model = mlflow.pyfunc.load_model(
                    f"models:/{model_name}@{registry.ALIAS_PRODUCTION}"
                )
                production_mae = evaluate_predictions(y_test, production_model.predict(X_test))[
                    "mae"
                ]
            except Exception:
                logger.exception(
                    "production_model_reevaluation_failed", extra={"model_name": model_name}
                )

        decision = registry.decide_promotion(
            candidate_mae=candidate_metrics["mae"],
            baseline_mae=baseline_metrics["mae"],
            production_mae=production_mae,
            improvement_threshold=settings.improvement_threshold,
        )
        mlflow.set_tag("promotion_decision", decision.reason)
        mlflow.log_metric("promoted", int(decision.promote))

        model_version = None
        if decision.promote:
            registered = mlflow.register_model(f"runs:/{run.info.run_id}/model", model_name)
            registry.promote(client, model_name, registered.version)
            model_version = registered.version

        logger.info(
            "training_cycle_complete",
            extra={
                "horizon_hours": horizon_hours,
                "candidate_mae": candidate_metrics["mae"],
                "baseline_mae": baseline_metrics["mae"],
                "production_mae": production_mae,
                "promoted": decision.promote,
                "reason": decision.reason,
            },
        )

        return {
            "horizon_hours": horizon_hours,
            "skipped": False,
            "run_id": run.info.run_id,
            "n_train": len(train_df),
            "n_test": len(test_df),
            "candidate_metrics": candidate_metrics,
            "baseline_metrics": baseline_metrics,
            "secondary_metrics": secondary_metrics,
            "production_mae": production_mae,
            "promoted": decision.promote,
            "promotion_reason": decision.reason,
            "model_version": model_version,
        }


def run_training_cycle(dag_run_id: str | None = None) -> None:
    with (
        session_scope() as session,
        track_run(
            session,
            dag_id="train_and_register_model",
            task_id="train_all_horizons",
            dag_run_id=dag_run_id,
        ) as run,
    ):
        summaries = [train_for_horizon(h, dag_run_id) for h in HORIZONS_HOURS]
        run.rows_processed = sum(s.get("n_train", 0) + s.get("n_test", 0) for s in summaries)
        run.extra = {"horizons": summaries}
