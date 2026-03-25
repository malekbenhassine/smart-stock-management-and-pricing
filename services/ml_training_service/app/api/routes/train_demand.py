from fastapi import APIRouter
from joblib import dump
from datetime import datetime
import json

from ...core.config import DATA_DIR, MODELS_DIR, REPORTS_DIR
from ...services.datasets import load_csv
from ...services.demand_ml_trainer import train_demand_ml

router = APIRouter(prefix="/train")


@router.post("/demand-ml")
def train_demand_ml_endpoint():
    sales = load_csv(DATA_DIR / "sales.csv")
    artifacts = train_demand_ml(sales)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    file_p10 = f"demand_ml_p10_{ts}.joblib"
    file_p50 = f"demand_ml_p50_{ts}.joblib"
    file_p90 = f"demand_ml_p90_{ts}.joblib"

    dump(artifacts.model_p10, MODELS_DIR / file_p10)
    dump(artifacts.model_p50, MODELS_DIR / file_p50)
    dump(artifacts.model_p90, MODELS_DIR / file_p90)

    meta = {
        "trained_at_utc": ts,
        "feature_cols": artifacts.feature_cols,
        "meta": artifacts.meta,
        "artifacts": {
            "p10": file_p10,
            "p50": file_p50,
            "p90": file_p90,
        },
    }

    report_path = REPORTS_DIR / f"demand_ml_meta_{ts}.json"
    report_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "ok", "meta": meta}