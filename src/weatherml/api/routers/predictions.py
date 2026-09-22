from datetime import UTC, datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from weatherml.api.deps import get_db
from weatherml.api.model_loader import model_cache
from weatherml.api.schemas import PredictRequest, PredictResponse
from weatherml.db.models import ModelPrediction
from weatherml.features.pipeline import build_features_for_location
from weatherml.ml import registry
from weatherml.ml.dataset import FEATURE_COLUMNS

router = APIRouter(tags=["predictions"])


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, db: Session = Depends(get_db)):
    loaded = model_cache.get(req.horizon_hours)
    if loaded is None:
        raise HTTPException(
            status_code=503,
            detail=f"no production model currently loaded for horizon {req.horizon_hours}h",
        )

    feature_row = build_features_for_location(db, req.location_id)
    if feature_row is None:
        raise HTTPException(
            status_code=404, detail="no observations available to build features for this location"
        )

    X = pd.DataFrame([{col: feature_row.get(col) for col in FEATURE_COLUMNS}])
    predicted_temp_c = round(float(loaded.model.predict(X)[0]), 2)

    now = datetime.now(UTC)
    model_name = registry.registered_model_name(req.horizon_hours)

    db.add(
        ModelPrediction(
            location_id=req.location_id,
            predicted_at=now,
            horizon_hours=req.horizon_hours,
            predicted_temp_c=predicted_temp_c,
            model_name=model_name,
            model_version=loaded.version,
            model_alias=registry.ALIAS_PRODUCTION,
            input_feature_time=feature_row["feature_time"],
        )
    )

    return PredictResponse(
        location_id=req.location_id,
        horizon_hours=req.horizon_hours,
        predicted_temp_c=predicted_temp_c,
        model_name=model_name,
        model_version=loaded.version,
        model_alias=registry.ALIAS_PRODUCTION,
        predicted_at=now,
        based_on_observation_time=feature_row["feature_time"],
    )
