import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import PredictionLog
from app.services.stock_client import get_recent_history_from_stock_service
from app.model_loader import get_model
from app.feature_builder import build_features
from app.schemas import BaseRequest, DemandResponse

MIN_HISTORY_DAYS_FOR_ML = 14


def _recent_sales(db: Session, req: BaseRequest, limit: int = 30):
    return get_recent_history_from_stock_service(product_id=req.product_id, limit=limit)


def _fallback_prediction(req: BaseRequest, history_rows):
    if history_rows:
        values = [float(r["sales"]) for r in history_rows if r.get("sales") is not None]
        avg_sales = float(np.mean(values)) if values else 0.0
        predicted = max(0.0, round(avg_sales, 1))
    else:
        # Si aucune vente connue, on estime à partir du seuil mini
        threshold_min = float(req.threshold_min or 0.0)
        predicted = max(1.0, round(threshold_min / 7, 1)) if threshold_min > 0 else 1.0

    return predicted


def forecast_demand_service(req: BaseRequest, db: Session) -> DemandResponse:
    history_rows = _recent_sales(db, req, limit=30)
    history_count = len(history_rows)

    # Fallback métier si historique insuffisant
    if history_count < MIN_HISTORY_DAYS_FOR_ML:
        predicted = _fallback_prediction(req, history_rows)
        conf_low = round(predicted * 0.80, 1)
        conf_high = round(predicted * 1.20, 1)

        log = PredictionLog(
            store_id=req.store_id,
            product_id=req.product_id,
            target_date=req.date,
            predicted_demand=predicted,
        )
        db.add(log)
        db.commit()

        return DemandResponse(
            store_id=req.store_id,
            product_id=req.product_id,
            date=req.date,
            predicted_demand=predicted,
            confidence_low=conf_low,
            confidence_high=conf_high,
            history_days_used=history_count,
        )

    model, trained_features, use_log = get_model()

    try:
        feature_row = build_features(
            db=db,
            store_id=req.store_id,
            product_id=req.product_id,
            target_date=req.date,
            price=req.price,
            stock=req.stock,
            discount=req.discount,
            competitor_pricing=req.competitor_pricing,
            units_ordered=req.units_ordered,
            weather_condition=req.weather_condition,
            category=req.category,
            region=req.region,
            trained_features=trained_features,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur feature engineering : {e}")

    X = pd.DataFrame([feature_row])
    raw_pred = float(model.predict(X)[0])

    predicted = float(np.expm1(raw_pred)) if use_log else raw_pred
    predicted = max(0.0, round(predicted, 1))

    conf_low = round(predicted * 0.85, 1)
    conf_high = round(predicted * 1.15, 1)

    log = PredictionLog(
        store_id=req.store_id,
        product_id=req.product_id,
        target_date=req.date,
        predicted_demand=predicted,
    )
    db.add(log)
    db.commit()

    return DemandResponse(
        store_id=req.store_id,
        product_id=req.product_id,
        date=req.date,
        predicted_demand=predicted,
        confidence_low=conf_low,
        confidence_high=conf_high,
        history_days_used=history_count,
    )