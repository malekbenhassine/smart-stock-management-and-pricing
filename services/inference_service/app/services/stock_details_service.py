from sqlalchemy.orm import Session

from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.demand_service import forecast_demand_service
from app.services.restock_service import recommend_restock_service
from app.services.stock_risk_service import predict_stock_risk_service
from app.services.anomaly_service import detect_anomalies_service
from app.services.explanation_builder import build_demand_explanation
from app.services.cold_start_service import get_sales_history_status


def get_stock_details_service(product_id: int, db: Session) -> dict:
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    history_status = get_sales_history_status(product_id=req.product_id)

    if history_status["is_cold_start"]:
        return {
            "product": product,
            "cold_start": True,
            "stock_module_enabled": False,
            "history_status": history_status,
            "demand_prediction": {
                "enabled": False,
                "status": "INSUFFICIENT_HISTORY",
                "p10": None,
                "p50": None,
                "p90": None,
                "history_days_used": history_status["history_count"],
                "required_history_days": history_status["required_history_days"],
                "explanation": history_status["message"],
            },
            "stock_risk": {
                "enabled": False,
                "product_id": product_id,
                "risk": "INSUFFICIENT_HISTORY",
                "risk_level": "INSUFFICIENT_HISTORY",
                "probability": None,
                "risk_probability": None,
                "likely_stockout": None,
                "forecast_weekly_demand": None,
                "coverage_weeks": None,
                "inputs": {
                    "current_stock": req.stock,
                    "threshold_min": req.threshold_min,
                    "threshold_max": req.threshold_max,
                    "forecast_weekly_demand": None,
                },
                "explanation": history_status["message"],
                "level": "INSUFFICIENT_HISTORY",
                "probability_value": None,
                "probability_percent": None,
                "analysis": history_status["message"],
                "message": history_status["message"],
                "stockout_probability": None,
            },
            "restock_recommendation": {
                "enabled": False,
                "status": "INSUFFICIENT_HISTORY",
                "recommended_qty": None,
                "lead_time_days": 7,
                "explanation": history_status["message"],
                "urgency": None,
                "days_of_stock_remaining": None,
                "predicted_demand": None,
            },
            "anomalies": {
                "enabled": False,
                "product_id": product_id,
                "anomaly_detected": False,
                "anomaly_score": None,
                "explanation": "Analyse des anomalies désactivée : historique insuffisant.",
                "anomalies": [],
            },
        }

    demand = forecast_demand_service(req, db)
    restock = recommend_restock_service(req, db)
    stock_risk = predict_stock_risk_service(product_id, db)
    anomalies = detect_anomalies_service(product_id, db)

    demand_prediction = {
        "enabled": True,
        "status": "OK",
        "p10": demand.confidence_low,
        "p50": demand.predicted_demand,
        "p90": demand.confidence_high,
        "history_days_used": demand.history_days_used,
        "required_history_days": history_status["required_history_days"],
        "explanation": build_demand_explanation(
            predicted_demand=demand.predicted_demand,
            history_days_used=demand.history_days_used,
        ),
    }

    restock_recommendation = {
        "enabled": True,
        "status": "OK",
        "recommended_qty": restock.recommended_order_qty,
        "lead_time_days": 7,
        "explanation": restock.reasoning,
        "urgency": restock.urgency,
        "days_of_stock_remaining": restock.days_of_stock_remaining,
        "predicted_demand": restock.predicted_demand,
    }

    return {
        "product": product,
        "cold_start": False,
        "stock_module_enabled": True,
        "history_status": history_status,
        "demand_prediction": demand_prediction,
        "stock_risk": stock_risk,
        "restock_recommendation": restock_recommendation,
        "anomalies": anomalies,
    }