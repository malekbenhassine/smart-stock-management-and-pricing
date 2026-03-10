from fastapi import APIRouter, HTTPException
import pandas as pd

from ...core.config import DATA_DIR, MODELS_DIR, REPORTS_DIR
from ...services.model_store import ModelStore
from ...services.anomaly_engine import AnomalyMLEngine

router = APIRouter(prefix="/detect")
store = ModelStore(MODELS_DIR)
engine = AnomalyMLEngine(store=store, reports_dir=REPORTS_DIR)

@router.get("/anomalies/{product_id}")
def detect_anomalies(product_id: int):
    try:
        products = pd.read_csv(DATA_DIR / "products.csv")
        competitor_prices = pd.read_csv(DATA_DIR / "competitor_prices.csv")

        prod_row = products[products["product_id"] == product_id]
        if prod_row.empty:
            return {"product_id": product_id, "anomalies": [], "error": "Produit introuvable"}

        return engine.detect_for_product_ml(
            product=prod_row.iloc[0].to_dict(),
            competitor_prices=competitor_prices
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))