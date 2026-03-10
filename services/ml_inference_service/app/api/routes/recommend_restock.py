from fastapi import APIRouter, HTTPException
import pandas as pd

from ...core.config import DATA_DIR, MODELS_DIR
from ...services.model_store import ModelStore
from ...services.demand_predictor import DemandPredictor
from ...services.restock_engine import RestockMLEngine

router = APIRouter(prefix="/recommend")

store = ModelStore(MODELS_DIR)
demand = DemandPredictor(DATA_DIR, MODELS_DIR) # utilise tes demand_ml_p10/p50/p90
engine = RestockMLEngine()

@router.get("/restock/{product_id}")
def recommend_restock(product_id: int):
    try:
        products = pd.read_csv(DATA_DIR / "products.csv")

        prod = products[products["product_id"] == product_id]
        if prod.empty:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        product = prod.iloc[0].to_dict()

        demand_pred = demand.predict_weekly(product_id)  # {p10,p50,p90,...}
        return engine.recommend(product=product, demand_pred=demand_pred)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))