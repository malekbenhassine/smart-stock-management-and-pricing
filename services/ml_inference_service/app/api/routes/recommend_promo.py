from fastapi import APIRouter, HTTPException
import pandas as pd

from ...core.config import DATA_DIR, MODELS_DIR
from ...services.model_store import ModelStore
from ...services.promo_engine import PromoMLEngine

router = APIRouter(prefix="/recommend")

store = ModelStore(MODELS_DIR)
engine = PromoMLEngine(store=store)

@router.get("/promo/{product_id}")
def recommend_promo(product_id: int):
    try:
        products = pd.read_csv(DATA_DIR / "products.csv")
        sales = pd.read_csv(DATA_DIR / "sales.csv")
        competitor_prices = pd.read_csv(DATA_DIR / "competitor_prices.csv")

        prod = products[products["product_id"] == product_id]
        if prod.empty:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        return engine.recommend(
            product=prod.iloc[0].to_dict(),
            sales=sales,
            competitor_prices=competitor_prices
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))