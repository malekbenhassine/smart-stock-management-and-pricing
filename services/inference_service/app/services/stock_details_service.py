from sqlalchemy.orm import Session

from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.demand_service import forecast_demand_service
from app.services.restock_service import recommend_restock_service
from app.services.stock_risk_service import predict_stock_risk_service
from app.services.anomaly_service import detect_anomalies_service


def get_stock_details_service(product_id: int, db: Session) -> dict:
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    demand = forecast_demand_service(req, db)
    restock = recommend_restock_service(req, db)
    stock_risk = predict_stock_risk_service(product_id, db)
    anomalies = detect_anomalies_service(product_id, db)

    demand_prediction = {
        "p10": demand.confidence_low,
        "p50": demand.predicted_demand,
        "p90": demand.confidence_high,
        "explanation": (
            f"Prévision calculée à partir de l’historique disponible "
            f"({demand.history_days_used} jour(s) utilisé(s))."
        ),
    }

    restock_recommendation = {
        "recommended_qty": restock.recommended_order_qty,
        "lead_time_days": 7,
        "explanation": restock.reasoning,
        "urgency": restock.urgency,
        "days_of_stock_remaining": restock.days_of_stock_remaining,
        "predicted_demand": restock.predicted_demand,
    }

    return {
        "product": product,
        "demand_prediction": demand_prediction,
        "stock_risk": stock_risk,
        "restock_recommendation": restock_recommendation,
        "anomalies": anomalies,
    }