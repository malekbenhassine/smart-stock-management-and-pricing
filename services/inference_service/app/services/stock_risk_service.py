import math
from sqlalchemy.orm import Session

from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.demand_service import forecast_demand_service


def predict_stock_risk_service(product_id: int, db: Session) -> dict:
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    demand_result = forecast_demand_service(req, db)

    # IMPORTANT:
    # on prend les valeurs normalisées depuis req, pas les clés brutes du product JSON
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
    explanation = "Le stock semble suffisant."

    if current_stock <= 0:
        risk = "STOCKOUT"
        likely_stockout = True
        probability = 1.0
        explanation = "Le stock est épuisé."
    elif weekly_demand <= 0:
        risk = "NORMAL"
        likely_stockout = False
        probability = 0.05
        explanation = "Aucune demande prévisionnelle significative détectée."
    elif current_stock < threshold_min:
        risk = "LOW_STOCK"
        likely_stockout = coverage_weeks < 1
        probability = min(1.0, max(0.6, weekly_demand / (current_stock + 1)))
        explanation = f"Le stock actuel ({current_stock:.0f}) est sous le seuil minimum ({threshold_min:.0f})."
    elif coverage_weeks < 1:
        risk = "STOCKOUT"
        likely_stockout = True
        probability = min(1.0, max(0.75, weekly_demand / (current_stock + 1)))
        explanation = (
            f"La demande prévue ({weekly_demand:.1f}/semaine) dépasse la capacité "
            f"de couverture du stock actuel ({current_stock:.0f})."
        )
    elif threshold_max > 0 and current_stock > threshold_max * 1.2:
        risk = "OVERSTOCK"
        likely_stockout = False
        probability = min(1.0, (current_stock - threshold_max) / max(threshold_max, 1))
        explanation = f"Le stock actuel ({current_stock:.0f}) dépasse sensiblement le seuil maximum ({threshold_max:.0f})."
    else:
        risk = "NORMAL"
        likely_stockout = False
        probability = min(1.0, weekly_demand / (current_stock + weekly_demand + 1))
        explanation = f"Le stock couvre environ {coverage_weeks:.2f} semaine(s) de demande prévue."

    probability = round(float(probability), 3)

    return {
        "product_id": product_id,
        "risk": risk,
        "risk_level": risk,
        "probability": probability,
        "risk_probability": probability,
        "likely_stockout": likely_stockout,
        "forecast_weekly_demand": round(weekly_demand, 2),
        "coverage_weeks": None if math.isinf(coverage_weeks) else round(coverage_weeks, 2),
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