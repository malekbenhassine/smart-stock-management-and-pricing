from fastapi import APIRouter
from joblib import dump
from datetime import datetime
import json
import pandas as pd

from ...core.config import DATA_DIR, MODELS_DIR, REPORTS_DIR
from ...services.price_recommender import train_price_demand_ml

router = APIRouter(prefix="/train")

@router.post("/price-ml")
def train_price_ml():
    products = pd.read_csv(DATA_DIR / "products.csv")
    sales = pd.read_csv(DATA_DIR / "sales.csv")
    competitor_prices = pd.read_csv(DATA_DIR / "competitor_prices.csv")
    promotions = pd.read_csv(DATA_DIR / "promotions.csv")

    art = train_price_demand_ml(products, sales, competitor_prices, promotions)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    dump(art.model_p10, MODELS_DIR / f"price_demand_p10_{ts}.joblib")
    dump(art.model_p50, MODELS_DIR / f"price_demand_p50_{ts}.joblib")
    dump(art.model_p90, MODELS_DIR / f"price_demand_p90_{ts}.joblib")

    meta = {
        "trained_at_utc": ts,
        "feature_cols": art.feature_cols,
        "meta": art.meta,
        "artifacts": {
            "p10": f"price_demand_p10_{ts}.joblib",
            "p50": f"price_demand_p50_{ts}.joblib",
            "p90": f"price_demand_p90_{ts}.joblib",
        }
    }
    (REPORTS_DIR / f"price_ml_meta_{ts}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return {"status": "ok", "meta": meta}