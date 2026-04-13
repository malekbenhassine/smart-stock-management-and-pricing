import os
import requests
from sqlalchemy.orm import Session
from ..models.tables import Product

ML_INFERENCE_URL = os.getenv("ML_INFERENCE_URL", "http://ml_inference_service:8020")
TIMEOUT = 15


def _call(endpoint: str) -> dict:
    try:
        r = requests.get(f"{ML_INFERENCE_URL}{endpoint}", timeout=TIMEOUT)
        r.raise_for_status()
        return {"ok": True, "data": r.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_ml_on_products(product_ids: list[int]) -> dict:
    results = {}
    for pid in product_ids:
        results[pid] = {
            "demand": _call(f"/predict/demand-weekly/{pid}"),
            "price": _call(f"/recommend/price/{pid}"),
            "restock": _call(f"/recommend/restock/{pid}"),
            "anomaly": _call(f"/detect/anomalies/{pid}"),
            "stock_risk": _call(f"/predict/stock-risk/{pid}"),
        }
    return results


def get_product_ids_from_db(db: Session) -> list[int]:
    rows = db.query(Product.id).all()
    return [r[0] for r in rows]