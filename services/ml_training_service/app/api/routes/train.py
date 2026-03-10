from fastapi import APIRouter
from joblib import dump
from datetime import datetime
import json

from ...core.config import DATA_DIR, MODELS_DIR, REPORTS_DIR
from ...services.datasets import load_all
from ...services.train_baselines import (
    build_weekly_sales,
    train_demand_baseline,
    train_price_rules,
    train_restock_rules,
    train_anomaly_rules,
)

router = APIRouter(prefix="/train")

@router.post("/all")
def train_all(horizon_weeks: int = 4):
    data = load_all(DATA_DIR)
    weekly = build_weekly_sales(data["sales"])

    demand_model = train_demand_baseline(weekly, horizon_weeks=horizon_weeks)
    price_rules = train_price_rules(data["products"], data["competitor_prices"])
    restock_rules = train_restock_rules(data["products"], data["product_suppliers"])
    anomaly_rules = train_anomaly_rules()

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    dump(demand_model, MODELS_DIR / f"demand_weekly_{ts}.joblib")
    dump(price_rules, MODELS_DIR / f"price_rules_{ts}.joblib")
    dump(restock_rules, MODELS_DIR / f"restock_rules_{ts}.joblib")
    dump(anomaly_rules, MODELS_DIR / f"anomaly_rules_{ts}.joblib")

    report = {
        "trained_at_utc": ts,
        "horizon_weeks": horizon_weeks,
        "artifacts": {
            "demand": f"demand_weekly_{ts}.joblib",
            "price_rules": f"price_rules_{ts}.joblib",
            "restock_rules": f"restock_rules_{ts}.joblib",
            "anomaly_rules": f"anomaly_rules_{ts}.joblib",
        },
        "counts": {
            "products": int(len(data["products"])),
            "sales_rows": int(len(data["sales"])),
            "competitor_prices_rows": int(len(data["competitor_prices"])),
        },
    }
    (REPORTS_DIR / f"train_report_{ts}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return {"status": "ok", "report": report}