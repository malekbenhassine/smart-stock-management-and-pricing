from fastapi import APIRouter
from joblib import dump
from datetime import datetime
import json

from ...core.config import MODELS_DIR, REPORTS_DIR, DATA_DIR
from ...services.datasets import load_all
from ...services.price_recommender import train_price_demand_ml

router = APIRouter(prefix="/train")


@router.post("/price-ml")
def train_price_ml():
    data = load_all(DATA_DIR)

    art = train_price_demand_ml(
        data["products"],
        data["sales"],
        data["competitor_prices"],
        data["promotions"],
    )

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    file_p10 = f"price_demand_p10_{ts}.joblib"
    file_p50 = f"price_demand_p50_{ts}.joblib"
    file_p90 = f"price_demand_p90_{ts}.joblib"

    dump(art.model_p10, MODELS_DIR / file_p10)
    dump(art.model_p50, MODELS_DIR / file_p50)
    dump(art.model_p90, MODELS_DIR / file_p90)

    meta = {
        "trained_at_utc": ts,
        "feature_cols": art.feature_cols,
        "meta": art.meta,
        "artifacts": {
            "p10": file_p10,
            "p50": file_p50,
            "p90": file_p90,
        },
    }

    report_path = REPORTS_DIR / f"price_ml_meta_{ts}.json"
    report_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"status": "ok", "meta": meta}