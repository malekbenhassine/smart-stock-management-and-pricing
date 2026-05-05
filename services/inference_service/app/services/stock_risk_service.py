import math
from sqlalchemy.orm import Session

from app.services.explanation_builder import build_stock_risk_explanation
from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.demand_service import forecast_demand_service
from app.services.cold_start_service import get_sales_history_status


def predict_stock_risk_service(product_id: int, db: Session) -> dict:
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    history_status = get_sales_history_status(product_id=req.product_id)

    if history_status["is_cold_start"]:
        return {
            "enabled": False,
            "product_id": product_id,
            "risk": "INSUFFICIENT_HISTORY",
            "risk_level": "INSUFFICIENT_HISTORY",
            "probability": None,
            "risk_probability": None,
            "likely_stockout": None,
            "forecast_weekly_demand": None,
            "coverage_weeks": None,
            "history_count": history_status["history_count"],
            "required_history_days": history_status["required_history_days"],
            "inputs": {
                "current_stock": float(req.stock or 0.0),
                "threshold_min": float(req.threshold_min or 0.0),
                "threshold_max": float(req.threshold_max or 0.0),
                "forecast_weekly_demand": None,
            },
            "explanation": history_status["message"],
            "level": "INSUFFICIENT_HISTORY",
            "probability_value": None,
            "probability_percent": None,
            "analysis": history_status["message"],
            "message": history_status["message"],
            "stockout_probability": None,
        }

    demand_result = forecast_demand_service(req, db)

    current_stock = float(req.stock or 0.0)
    threshold_min = float(req.threshold_min or 0.0)
    threshold_max = float(req.threshold_max or 0.0)
    weekly_demand = float(demand_result.predicted_demand)

    if weekly_demand > 0:
        coverage_weeks = current_stock / weekly_demand
    else:
        coverage_weeks = math.inf

    likely_stockout = False
    probability = 0.0
    risk = "NORMAL"

    if current_stock <= 0:
        risk = "STOCKOUT"
        likely_stockout = True
        probability = 1.0
    elif weekly_demand <= 0:
        risk = "NORMAL"
        likely_stockout = False
        probability = 0.05
    elif current_stock < threshold_min:
        risk = "LOW_STOCK"
        likely_stockout = coverage_weeks < 1
        probability = min(1.0, max(0.6, weekly_demand / (current_stock + 1)))
    elif coverage_weeks < 1:
        risk = "STOCKOUT"
        likely_stockout = True
        probability = min(1.0, max(0.75, weekly_demand / (current_stock + 1)))
    elif threshold_max > 0 and current_stock > threshold_max * 1.2:
        risk = "OVERSTOCK"
        likely_stockout = False
        probability = min(1.0, (current_stock - threshold_max) / max(threshold_max, 1))
    else:
        risk = "NORMAL"
        likely_stockout = False
        probability = min(1.0, weekly_demand / (current_stock + weekly_demand + 1))

    probability = round(float(probability), 3)

    explanation = build_stock_risk_explanation(
        risk=risk,
        current_stock=current_stock,
        threshold_min=threshold_min,
        threshold_max=threshold_max,
        weekly_demand=weekly_demand,
        coverage_weeks=None if math.isinf(coverage_weeks) else coverage_weeks,
    )

    return {
        "enabled": True,
        "product_id": product_id,
        "risk": risk,
        "risk_level": risk,
        "probability": probability,
        "risk_probability": probability,
        "likely_stockout": likely_stockout,
        "forecast_weekly_demand": round(weekly_demand, 2),
        "coverage_weeks": None if math.isinf(coverage_weeks) else round(coverage_weeks, 2),
        "history_count": history_status["history_count"],
        "required_history_days": history_status["required_history_days"],
        "inputs": {
            "current_stock": current_stock,
            "threshold_min": threshold_min,
            "threshold_max": threshold_max,
            "forecast_weekly_demand": round(weekly_demand, 2),
        },
        "explanation": explanation,
        "level": risk,
        "probability_value": probability,
        "probability_percent": round(probability * 100, 1),
        "analysis": explanation,
        "message": explanation,
        "stockout_probability": round(probability * 100, 1),
    }