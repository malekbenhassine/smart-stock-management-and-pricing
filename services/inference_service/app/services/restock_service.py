from sqlalchemy.orm import Session

from app.database import PredictionLog
from app.schemas import BaseRequest, RestockResponse
from app.services.demand_service import forecast_demand_service
from app.services.stock_client import get_recent_history_from_stock_service

OBSERVATION_WINDOW_DAYS = 30
FORECAST_HORIZON_DAYS = 7
SALE_MOVEMENT_JUSTIFICATIONS = {"VENTE_CLIENT", "COMMANDE_CLIENT_LIVREE"}


def _recent_sales(db: Session, req: BaseRequest, limit: int = 365):
    return get_recent_history_from_stock_service(product_id=req.product_id, limit=limit)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fallback_weekly_demand(req: BaseRequest, history_rows) -> float:
    """
    Fallback en unités / 7 jours.

    Correction : avant, on faisait parfois une moyenne seulement sur les jours avec vente.
    Maintenant, on divise par une fenêtre de 30 jours pour rester cohérent avec le bloc KPI.
    """
    total_sales = 0.0

    for row in history_rows or []:
        if row.get("sales") is not None:
            total_sales += max(0.0, _safe_float(row.get("sales")))

    if total_sales > 0:
        return round((total_sales / OBSERVATION_WINDOW_DAYS) * FORECAST_HORIZON_DAYS, 2)

    threshold_min = _safe_float(req.threshold_min)

    if threshold_min > 0:
        return round(max(1.0, threshold_min / 2.0), 2)

    return 1.0


def _compute_urgency(days_remaining: float, restock_needed: bool) -> str:
    if not restock_needed:
        return "low"

    if days_remaining <= 7:
        return "critical"

    if days_remaining <= 14:
        return "high"

    if days_remaining <= 30:
        return "medium"

    return "low"


def _build_reasoning(
    current_stock: float,
    weekly_demand: float,
    weeks_remaining: float,
    restock_needed: bool,
    recommended_qty: float,
    threshold_min: float,
    reorder_point: float,
) -> str:
    if restock_needed:
        return (
            f"Réassort recommandé : le stock actuel est de {current_stock:.0f} unité(s), "
            f"la demande prévue est de {weekly_demand:.1f} unité(s) sur les 7 prochains jours, "
            f"et le point de commande est estimé à {reorder_point:.0f} unité(s). "
            f"Commander {recommended_qty:.0f} unité(s) pour revenir vers le niveau cible."
        )

    return (
        f"Aucun réassort nécessaire : le stock actuel est de {current_stock:.0f} unité(s), "
        f"la demande prévue est de {weekly_demand:.1f} unité(s) sur les 7 prochains jours, "
        f"avec une couverture estimée à {weeks_remaining:.2f} semaine(s). "
        f"Le stock est supérieur au seuil minimum de {threshold_min:.0f} unité(s)."
    )


def recommend_restock_service(req: BaseRequest, db: Session) -> RestockResponse:
    current_stock = _safe_float(req.stock)
    threshold_min = _safe_float(req.threshold_min)
    threshold_max = _safe_float(req.threshold_max)

    history_rows = _recent_sales(db, req, limit=365)

    try:
        demand_result = forecast_demand_service(req, db)
        weekly_demand = _safe_float(demand_result.predicted_demand)
    except Exception:
        weekly_demand = _fallback_weekly_demand(req, history_rows)

    if weekly_demand <= 0:
        weekly_demand = _fallback_weekly_demand(req, history_rows)

    if weekly_demand > 0:
        weeks_remaining = round(current_stock / weekly_demand, 2)
        days_remaining = round(weeks_remaining * 7, 1)
    else:
        weeks_remaining = 999.0
        days_remaining = 999.0

    safety_stock = weekly_demand * 2
    reorder_point = max(threshold_min, weekly_demand + safety_stock)

    restock_needed = (
        current_stock <= threshold_min
        or weeks_remaining <= 2
        or current_stock <= reorder_point
    )

    if restock_needed:
        if threshold_max > 0:
            target_stock = threshold_max
        else:
            target_stock = current_stock + weekly_demand * 4

        recommended_qty = max(0.0, target_stock - current_stock)
    else:
        recommended_qty = 0.0

    urgency = _compute_urgency(
        days_remaining=days_remaining,
        restock_needed=restock_needed,
    )

    reasoning = _build_reasoning(
        current_stock=current_stock,
        weekly_demand=weekly_demand,
        weeks_remaining=weeks_remaining,
        restock_needed=restock_needed,
        recommended_qty=recommended_qty,
        threshold_min=threshold_min,
        reorder_point=reorder_point,
    )

    log = PredictionLog(
        store_id=req.store_id,
        product_id=req.product_id,
        target_date=req.date,
        predicted_demand=weekly_demand,
        restock_needed=restock_needed,
        restock_qty=recommended_qty,
    )

    db.add(log)
    db.commit()

    return RestockResponse(
        store_id=req.store_id,
        product_id=req.product_id,
        date=req.date,
        current_stock=current_stock,
        predicted_demand=round(weekly_demand, 2),
        restock_needed=restock_needed,
        recommended_order_qty=round(recommended_qty, 0),
        days_of_stock_remaining=days_remaining,
        urgency=urgency,
        reasoning=reasoning,
    )
