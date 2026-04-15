import numpy as np
import pandas as pd
from datetime import timedelta
from sqlalchemy.orm import Session
from app.services.explanation_builder import build_restock_explanation
from app.database import PredictionLog
from app.services.stock_client import get_recent_history_from_stock_service
from app.schemas import BaseRequest, RestockResponse
from app.model_loader import get_model
from app.feature_builder import build_features
from app.core.config import RESTOCK_THRESHOLD, RESTOCK_MULTIPLIER

MIN_HISTORY_DAYS_FOR_ML = 14


def _recent_sales(db: Session, req: BaseRequest, limit: int = 30):
    return get_recent_history_from_stock_service(product_id=req.product_id, limit=limit)


def _fallback_daily_demand(req: BaseRequest, history_rows):
    if history_rows:
        values = [float(r["sales"]) for r in history_rows if r.get("sales") is not None]
        return float(np.mean(values)) if values else 0.0

    threshold_min = float(req.threshold_min or 0.0)
    return max(1.0, threshold_min / 7) if threshold_min > 0 else 1.0


def _predict_one_day(model, trained_features, use_log, db, req, target_date, price, stock):
    feature_row = build_features(
        db=db,
        store_id=req.store_id,
        product_id=req.product_id,
        target_date=target_date,
        price=price,
        stock=stock,
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


def recommend_restock_service(req: BaseRequest, db: Session) -> RestockResponse:
    history_rows = _recent_sales(db, req, limit=30)
    history_count = len(history_rows)

    if history_count < MIN_HISTORY_DAYS_FOR_ML:
        avg_daily_demand = round(_fallback_daily_demand(req, history_rows), 1)
        threshold_min = float(req.threshold_min or 0.0)
        threshold_max = float(req.threshold_max or 0.0)

        if avg_daily_demand > 0:
            days_remaining = round(req.stock / avg_daily_demand, 1)
        else:
            days_remaining = 999.0

        restock_needed = req.stock <= threshold_min
        recommended_qty = max(0.0, threshold_max - req.stock) if restock_needed else 0.0

        if days_remaining <= 1:
            urgency = "critical"
        elif days_remaining <= 3:
            urgency = "high"
        elif days_remaining <= 7:
            urgency = "medium"
        else:
            urgency = "low"

        reasoning = build_restock_explanation(
            current_stock=req.stock,
            predicted_demand=avg_daily_demand,
            recommended_qty=recommended_qty,
            days_remaining=days_remaining,
            urgency=urgency,
            threshold_min=threshold_min,
            threshold_max=threshold_max,
            used_rule_based=True,
        )

        log = PredictionLog(
            store_id=req.store_id,
            product_id=req.product_id,
            target_date=req.date,
            predicted_demand=avg_daily_demand,
            restock_needed=restock_needed,
            restock_qty=recommended_qty,
        )
        db.add(log)
        db.commit()

        return RestockResponse(
            store_id=req.store_id,
            product_id=req.product_id,
            date=req.date,
            current_stock=req.stock,
            predicted_demand=avg_daily_demand,
            restock_needed=restock_needed,
            recommended_order_qty=round(recommended_qty, 0),
            days_of_stock_remaining=days_remaining,
            urgency=urgency,
            reasoning=reasoning,
        )

    model, trained_features, use_log = get_model()

    daily_demands = []
    for offset in range(7):
        day = req.date + timedelta(days=offset)
        d = _predict_one_day(model, trained_features, use_log, db, req, day, req.price, req.stock)
        daily_demands.append(d)

    avg_daily_demand = float(np.mean(daily_demands))
    total_7d_demand = float(np.sum(daily_demands))

    days_remaining = round(req.stock / avg_daily_demand, 1) if avg_daily_demand > 0 else 999.0
    restock_needed = req.stock < (RESTOCK_THRESHOLD * total_7d_demand)

    if restock_needed:
        target_stock = RESTOCK_MULTIPLIER * total_7d_demand
        order_qty = round(max(0.0, target_stock - req.stock), 0)
    else:
        order_qty = 0.0

    if days_remaining <= 1:
        urgency = "critical"
    elif days_remaining <= 3:
        urgency = "high"
    elif days_remaining <= 7:
        urgency = "medium"
    else:
        urgency = "low"

    reasoning = (
        f"Stock faible ({req.stock:.0f} unités). Commander {order_qty:.0f} unités."
        if restock_needed
        else f"Stock suffisant ({req.stock:.0f} unités) pour environ {days_remaining:.1f} jours."
    )

    log = PredictionLog(
        store_id=req.store_id,
        product_id=req.product_id,
        target_date=req.date,
        predicted_demand=avg_daily_demand,
        restock_needed=restock_needed,
        restock_qty=order_qty,
    )
    db.add(log)
    db.commit()

    return RestockResponse(
        store_id=req.store_id,
        product_id=req.product_id,
        date=req.date,
        current_stock=req.stock,
        predicted_demand=round(avg_daily_demand, 1),
        restock_needed=restock_needed,
        recommended_order_qty=order_qty,
        days_of_stock_remaining=days_remaining,
        urgency=urgency,
        reasoning=reasoning,
    )