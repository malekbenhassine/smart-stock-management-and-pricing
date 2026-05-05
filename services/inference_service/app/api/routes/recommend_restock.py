from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import math

from app.database import get_db
from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.restock_service import recommend_restock_service
from app.services.cold_start_service import get_sales_history_status

router = APIRouter(prefix="/recommend")


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


@router.get("/restock/{product_id}")
def recommend_restock(product_id: int, db: Session = Depends(get_db)):
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    history_status = get_sales_history_status(product_id=req.product_id)

    if history_status["is_cold_start"]:
        return {
            "product_id": product_id,
            "supplier_id": 0,
            "enabled": False,
            "status": "INSUFFICIENT_HISTORY",
            "cold_start": True,
            "history_count": history_status["history_count"],
            "required_history_days": history_status["required_history_days"],
            "recommended_qty": None,
            "interval": {
                "low": None,
                "high": None,
            },
            "lead_time_days": 7,
            "last_cost_price": _safe_float(
                product.get("cost_price", product.get("prixCout", 0.0))
            ),
            "reorder_point": None,
            "safety_stock": None,
            "target_level": None,
            "stock_status": "disabled",
            "service_level": 0.95,
            "explanation": history_status["message"],
            "estimated_impact": {
                "forecast_p10_lead_time": None,
                "forecast_p50_lead_time": None,
                "forecast_p90_lead_time": None,
            },
        }

    result = recommend_restock_service(req, db)

    threshold_min = _safe_float(
        product.get("threshold_min", product.get("seuilMin", 0.0))
    )

    threshold_max = _safe_float(
        product.get("threshold_max", product.get("seuilMax", 0.0))
    )

    current_stock = _safe_float(result.current_stock)
    predicted_weekly_demand = _safe_float(result.predicted_demand)
    recommended_qty = _safe_float(result.recommended_order_qty)

    safety_stock = predicted_weekly_demand * 2
    reorder_point = max(threshold_min, predicted_weekly_demand + safety_stock)

    if recommended_qty > 0:
        target_level = current_stock + recommended_qty
    else:
        target_level = current_stock

    if threshold_max > 0 and target_level > threshold_max:
        target_level = threshold_max

    stock_status = (
        "critical" if result.days_of_stock_remaining <= 7 and result.restock_needed
        else "reorder" if result.restock_needed
        else "normal"
    )

    return {
        "product_id": product_id,
        "supplier_id": 0,
        "enabled": True,
        "status": "OK",
        "cold_start": False,
        "history_count": history_status["history_count"],
        "required_history_days": history_status["required_history_days"],
        "recommended_qty": int(round(recommended_qty)),
        "interval": {
            "low": max(0, int(round(recommended_qty * 0.8))),
            "high": int(round(recommended_qty * 1.2)),
        },
        "lead_time_days": 7,
        "last_cost_price": _safe_float(
            product.get("cost_price", product.get("prixCout", 0.0))
        ),
        "reorder_point": int(math.ceil(reorder_point)),
        "safety_stock": round(safety_stock, 2),
        "target_level": int(math.ceil(target_level)),
        "stock_status": stock_status,
        "service_level": 0.95,
        "explanation": result.reasoning,
        "estimated_impact": {
            "forecast_p10_lead_time": round(predicted_weekly_demand * 0.85, 2),
            "forecast_p50_lead_time": round(predicted_weekly_demand, 2),
            "forecast_p90_lead_time": round(predicted_weekly_demand * 1.15, 2),
        },
    }