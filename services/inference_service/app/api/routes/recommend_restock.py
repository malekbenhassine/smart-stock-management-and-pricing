from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import math

from app.database import get_db
from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.restock_service import recommend_restock_service

router = APIRouter(prefix="/recommend")


@router.get("/restock/{product_id}")
def recommend_restock(product_id: int, db: Session = Depends(get_db)):
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    result = recommend_restock_service(req, db)

    threshold_min = int(product.get("threshold_min", 0))
    threshold_max = int(product.get("threshold_max", 0))
    reorder_point = max(threshold_min, math.ceil(result.predicted_demand * 7))
    target_level = max(threshold_max, math.ceil(result.current_stock + result.recommended_order_qty))

    return {
        "product_id": product_id,
        "supplier_id": 0,
        "recommended_qty": int(result.recommended_order_qty),
        "interval": {
            "low": max(0, int(result.recommended_order_qty * 0.8)),
            "high": int(result.recommended_order_qty * 1.2),
        },
        "lead_time_days": 7,
        "last_cost_price": product.get("cost_price", 0.0),
        "reorder_point": reorder_point,
        "safety_stock": round(result.predicted_demand * 2, 2),
        "target_level": target_level,
        "stock_status": (
            "critical" if result.days_of_stock_remaining <= 1
            else "reorder" if result.restock_needed
            else "normal"
        ),
        "service_level": 0.95,
        "explanation": result.reasoning,
        "estimated_impact": {
            "forecast_p10_lead_time": round(result.predicted_demand * 0.85, 2),
            "forecast_p50_lead_time": round(result.predicted_demand, 2),
            "forecast_p90_lead_time": round(result.predicted_demand * 1.15, 2),
        }
    }