from fastapi import APIRouter, HTTPException
import pandas as pd

from ...core.config import DATA_DIR, MODELS_DIR
from ...services.demand_predictor import DemandPredictor
from ...services.restock_engine import RestockMLEngine

router = APIRouter(prefix="/recommend")

demand = DemandPredictor(DATA_DIR, MODELS_DIR)
engine = RestockMLEngine()


@router.get("/restock/{product_id}")
def recommend_restock(product_id: int):
    try:
        products = pd.read_csv(DATA_DIR / "products.csv")
        product_suppliers = pd.read_csv(DATA_DIR / "product_suppliers.csv")

        prod = products[products["product_id"] == product_id]
        if prod.empty:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        supplier_rows = product_suppliers[product_suppliers["product_id"] == product_id]
        if supplier_rows.empty:
            raise HTTPException(
                status_code=404,
                detail="Aucun fournisseur trouvé pour ce produit"
            )

        product = prod.iloc[0].to_dict()
        demand_pred = demand.predict_weekly(product_id)

        result = engine.recommend(
            product=product,
            demand_pred=demand_pred,
            supplier_rows=supplier_rows
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))