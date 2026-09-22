from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from weatherml.api.deps import get_db
from weatherml.api.model_loader import model_cache

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    models_loaded = {f"{h}h": model_cache.get(h) is not None for h in model_cache.horizons}

    if not db_ok:
        raise HTTPException(
            status_code=503, detail={"db_ok": db_ok, "models_loaded": models_loaded}
        )

    return {"db_ok": db_ok, "models_loaded": models_loaded}
