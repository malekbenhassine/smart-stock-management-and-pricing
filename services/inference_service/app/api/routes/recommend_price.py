from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.price_service import recommend_price_service

router = APIRouter(prefix="/recommend")


@router.get("/price/{product_id}")
def recommend_price(product_id: int, db: Session = Depends(get_db)):
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    result = recommend_price_service(req, db)

    cost_price = float(product.get("cost_price", 0.0))
    min_margin = float(product.get("min_margin", 0.0))

    if cost_price > 0:
        min_allowed_price = round(cost_price * (1 + min_margin), 2)
    else:
        min_allowed_price = round(result.current_price * 0.8, 2)

    return {
        "product_id": product_id,
        "recommended_price": max(round(result.recommended_price, 2), min_allowed_price),
        "interval": {
            "low": min_allowed_price,
            "high": round(result.current_price * 1.2, 2),
        },
        "direction": (
            "UP" if result.recommended_price > result.current_price
            else "DOWN" if result.recommended_price < result.current_price
            else "STABLE"
        ),
        "demand_weekly": {
            "p10": round(result.predicted_demand_at_recommended_price * 0.85, 2),
            "p50": round(result.predicted_demand_at_recommended_price, 2),
            "p90": round(result.predicted_demand_at_recommended_price * 1.15, 2),
        },
        "estimated_margin_impact_week": 0.0,
        "explanation": result.reasoning,
    }