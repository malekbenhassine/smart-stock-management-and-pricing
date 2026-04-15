import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.database import PredictionLog
from app.services.stock_client import get_recent_history_from_stock_service
from app.schemas import BaseRequest, PricingResponse
from app.model_loader import get_model
from app.feature_builder import build_features
from app.core.config import MAX_PRICE_CHANGE
from app.services.explanation_builder import build_price_explanation


def _predict_demand_for_price(
    model, trained_features, use_log, db, req, test_price: float
) -> float:
    feature_row = build_features(
        db=db,
        store_id=req.store_id,
        product_id=req.product_id,
        target_date=req.date,
        price=test_price,
        stock=req.stock,
        discount=req.discount,
        competitor_pricing=req.competitor_pricing,
        units_ordered=req.units_ordered,
        weather_condition=req.weather_condition,
        category=req.category,
        region=req.region,
        trained_features=trained_features,
    )
    X = pd.DataFrame([feature_row])
    raw = float(model.predict(X)[0])
    pred = float(np.expm1(raw)) if use_log else raw
    return max(0.0, pred)


def recommend_price_service(req: BaseRequest, db: Session) -> PricingResponse:
    model, trained_features, use_log = get_model()

    current_price = float(req.price)
    current_stock = float(req.stock)
    threshold_min = float(req.threshold_min or 0.0)
    threshold_max = float(req.threshold_max or 0.0)
    min_price = float(req.min_price) if req.min_price is not None else current_price
    cost_price = float(req.cost_price) if req.cost_price is not None else 0.0
    min_margin = float(req.min_margin) if getattr(req, "min_margin", None) is not None else 0.0

    safe_floor = max(min_price, cost_price)

    # Fallback : historique insuffisant
    history_count = len(
        get_recent_history_from_stock_service(product_id=req.product_id, limit=30)
    )

    if history_count < 14:
        recommended_price = current_price
        reasoning = (
            "Prix actuel conservé : historique réel insuffisant pour une recommandation fiable."
        )

        if threshold_max > 0:
            overstock_ratio = current_stock / threshold_max

            if overstock_ratio >= 1.35:
                candidate = round(current_price * 0.95, 2)
                recommended_price = max(safe_floor, candidate)
                reasoning = (
                    "Baisse modérée recommandée : surstock important avec historique insuffisant. "
                    "Réduction prudente tout en respectant le prix minimum."
                )
            elif overstock_ratio >= 1.15:
                candidate = round(current_price * 0.98, 2)
                recommended_price = max(safe_floor, candidate)
                reasoning = (
                    "Baisse légère recommandée : stock élevé avec historique insuffisant. "
                    "Réduction prudente pour favoriser l'écoulement."
                )

        if threshold_min > 0 and current_stock <= threshold_min:
            recommended_price = current_price
            reasoning = (
                "Prix actuel conservé : stock faible et historique insuffisant. "
                "Aucune hausse automatique n'est appliquée sans données fiables."
            )

        price_change_pct = (
            round(((recommended_price - current_price) / current_price) * 100, 2)
            if current_price > 0 else 0.0
        )

        return PricingResponse(
            store_id=req.store_id,
            product_id=req.product_id,
            date=req.date,
            current_price=current_price,
            recommended_price=round(recommended_price, 2),
            price_change_pct=price_change_pct,
            predicted_demand_at_current_price=0.0,
            predicted_demand_at_recommended_price=0.0,
            reasoning=reasoning,
        )

    # Recommandation ML
    min_price_ml = current_price * (1 - MAX_PRICE_CHANGE)
    max_price_ml = current_price * (1 + MAX_PRICE_CHANGE)

    min_price_ml = max(min_price_ml, safe_floor)

    price_grid = np.linspace(min_price_ml, max_price_ml, 21)

    demand_at_current = _predict_demand_for_price(
        model, trained_features, use_log, db, req, current_price
    )

    best_price = current_price
    best_revenue = current_price * demand_at_current
    best_demand = demand_at_current

    for test_price in price_grid:
        test_price = round(float(test_price), 2)
        demand = _predict_demand_for_price(
            model, trained_features, use_log, db, req, test_price
        )
        revenue = test_price * demand

        if revenue > best_revenue:
            best_revenue = revenue
            best_price = test_price
            best_demand = demand

    best_price = float(round(best_price, 2))
    best_demand = float(round(best_demand, 1))
    demand_at_current = float(round(demand_at_current, 1))
    change_pct = float(round((best_price - current_price) / current_price * 100, 2))

    if abs(change_pct) < 1.0:
        reasoning = "Le prix actuel est déjà proche de l'optimal."
    elif change_pct > 0:
        reasoning = f"Augmenter le prix de {change_pct:.1f} % devrait générer un revenu supérieur."
    else:
        reasoning = f"Baisser le prix de {abs(change_pct):.1f} % devrait améliorer le revenu total."

    log = PredictionLog(
        store_id=req.store_id,
        product_id=req.product_id,
        target_date=req.date,
        predicted_demand=best_demand,
        recommended_price=best_price,
    )
    db.add(log)
    db.commit()

    return PricingResponse(
        store_id=req.store_id,
        product_id=req.product_id,
        date=req.date,
        current_price=current_price,
        recommended_price=best_price,
        price_change_pct=change_pct,
        predicted_demand_at_current_price=demand_at_current,
        predicted_demand_at_recommended_price=best_demand,
        reasoning=reasoning,
    )


def build_price_recommendation_response(product: dict, result: PricingResponse) -> dict:
    current_price = float(result.current_price)
    recommended_price_raw = float(result.recommended_price)
    predicted_current = float(result.predicted_demand_at_current_price or 0.0)
    predicted_recommended = float(result.predicted_demand_at_recommended_price or 0.0)

    cost_price = float(product.get("cost_price", 0.0))
    min_margin = float(product.get("min_margin", 0.0))

    if cost_price > 0:
        min_allowed_price = round(cost_price * (1 + min_margin), 2)
    else:
        min_allowed_price = round(current_price * 0.8, 2)

    final_recommended_price = max(round(recommended_price_raw, 2), min_allowed_price)

    direction = (
        "UP" if final_recommended_price > current_price
        else "DOWN" if final_recommended_price < current_price
        else "STABLE"
    )

    explanation = build_price_explanation(
        current_price=current_price,
        recommended_price=final_recommended_price,
        predicted_demand=predicted_recommended,
        price_direction=direction,
    )

    current_margin_per_unit = max(current_price - cost_price, 0.0)
    recommended_margin_per_unit = max(final_recommended_price - cost_price, 0.0)

    current_margin_week = current_margin_per_unit * predicted_current
    recommended_margin_week = recommended_margin_per_unit * predicted_recommended

    estimated_margin_impact_week = round(
        recommended_margin_week - current_margin_week, 2
    )

    return {
        "product_id": result.product_id,
        "recommended_price": final_recommended_price,
        "interval": {
            "low": min_allowed_price,
            "high": round(current_price * 1.2, 2),
        },
        "direction": direction,
        "demand_weekly": {
            "p10": round(predicted_recommended * 0.85, 2),
            "p50": round(predicted_recommended, 2),
            "p90": round(predicted_recommended * 1.15, 2),
        },
        "estimated_margin_impact_week": estimated_margin_impact_week,
        "explanation": explanation,
    }