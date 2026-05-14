from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.feature_builder import build_features_for_model, load_demand_features
from app.services.request_builder import build_demand_request
from app.services.stock_client import (
    get_product_by_id,
    get_recent_history_from_stock_service,
)


APP_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = APP_DIR / "models"

MODEL_PATH = MODELS_DIR / "demand_model.pkl"
FEATURES_PATH = MODELS_DIR / "demand_features.pkl"
LOG_PATH = MODELS_DIR / "use_log_transform.pkl"

MIN_HISTORY_DAYS = 14
HISTORY_LIMIT_FOR_MODEL = 140


def _load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Modèle introuvable : {MODEL_PATH}")
    return joblib.load(MODEL_PATH)


def _load_log_flag() -> bool:
    if LOG_PATH.exists():
        try:
            return bool(joblib.load(LOG_PATH))
        except Exception:
            return False
    return False


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _history_sales(rows: list[dict]) -> list[float]:
    values = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue

        value = (
            row.get("units_sold")
            if row.get("units_sold") is not None
            else row.get("sales")
            if row.get("sales") is not None
            else row.get("qty")
        )
        values.append(_safe_float(value, 0.0))

    return values


def observed_weekly_demand(history_rows: list[dict], days: int = 30) -> float:
    """
    Vitesse réelle :
    somme des 30 dernières observations / 30 * 7.
    Ne jamais sommer 365 jours puis diviser par 30.
    """
    values = _history_sales(history_rows)
    if not values:
        return 0.0

    recent = values[-days:]
    if not recent:
        return 0.0

    return round((sum(recent) / max(len(recent), 1)) * 7, 2)


def recent_sales_7d(history_rows: list[dict]) -> float:
    values = _history_sales(history_rows)
    return round(sum(values[-7:]), 2) if values else 0.0


def predict_demand(product_or_id: Any, context: dict | None = None) -> dict:
    """
    Retourne une prévision de demande sur 7 jours.
    Compatible avec product id, SKU ou objet produit.
    """
    context = context or {}

    if isinstance(product_or_id, (int, str)):
        product = get_product_by_id(product_or_id) or {"id": product_or_id, "sku": str(product_or_id)}
    else:
        product = product_or_id

    req = build_demand_request(product, context=context)

    # Priorité au SKU, car stock_service historique est par SKU
    history_key = req.sku or req.product_id
    history_rows = get_recent_history_from_stock_service(
        product_id=history_key,
        limit=HISTORY_LIMIT_FOR_MODEL,
    )

    history_count = len(history_rows)
    history_days = history_count

    if history_days < MIN_HISTORY_DAYS:
        return {
            "status": "cold_start",
            "cold_start": True,
            "history_days": history_days,
            "history_count": history_count,
            "minimum_required_days": MIN_HISTORY_DAYS,
            "predicted_demand": 0.0,
            "predicted_demand_7d": 0.0,
            "weekly_demand": 0.0,
            "message": "Historique de ventes insuffisant pour une prévision fiable.",
        }

    model = _load_model()
    demand_features = load_demand_features()
    X = build_features_for_model(req, history_rows, demand_features=demand_features)

    raw_pred = float(model.predict(X)[0])
    use_log = _load_log_flag()

    if use_log:
        pred = float(np.expm1(raw_pred))
    else:
        pred = raw_pred

    pred = max(0.0, pred)

    observed_30d_weekly = observed_weekly_demand(history_rows, days=30)
    observed_7d = recent_sales_7d(history_rows)

    return {
        "status": "ok",
        "cold_start": False,
        "history_days": history_days,
        "history_count": history_count,
        "minimum_required_days": MIN_HISTORY_DAYS,
        "predicted_demand": round(pred, 2),
        "predicted_demand_7d": round(pred, 2),
        "weekly_demand": round(pred, 2),
        "observed_weekly_30d": observed_30d_weekly,
        "recent_sales_7d": observed_7d,
        "model_features_count": len(demand_features),
        "message": "Prévision ML générée sur 7 jours.",
    }


# Alias possibles attendus par d'autres services
forecast_demand = predict_demand
get_demand_forecast = predict_demand
predict_weekly_demand = predict_demand



def forecast_demand_service(req, db=None):
    """
    Wrapper compatible avec restock_service, stock_risk_service et dashboard_service.
    Retourne un objet avec l'attribut .predicted_demand attendu par l'ancien code.
    """
    from types import SimpleNamespace

    result = predict_demand(req)
    weekly = _safe_float(
        result.get("weekly_demand") or result.get("predicted_demand_7d") or result.get("predicted_demand"),
        0.0,
    )
    return SimpleNamespace(
        predicted_demand=weekly,
        predicted_demand_7d=weekly,
        weekly_demand=weekly,
        status=result.get("status", "ok"),
        cold_start=bool(result.get("cold_start", False)),
        history_days=int(result.get("history_days", result.get("history_count", 0)) or 0),
        raw=result,
    )
