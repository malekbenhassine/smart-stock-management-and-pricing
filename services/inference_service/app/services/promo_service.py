from sqlalchemy.orm import Session

from app.services.stock_client import (
    get_product_from_stock_service,
    get_elimination_recommendation_from_stock_service,
)
from app.services.request_builder import build_request_from_product
from app.services.restock_service import recommend_restock_service


LIQUIDATION_ACTIONS = {
    "LIQUIDATION_OR_PROMO",
    "ELIMINATION_PROGRESSIVE",
    "ELIMINATION_DEFINITIVE",
}

LIQUIDATION_STATUSES = {
    "LIQUIDATION_CANDIDATE",
    "ELIMINATION_CANDIDATE",
    "DEAD_STOCK",
}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_upper(value) -> str:
    return str(value or "").strip().upper()


def _extract_elimination_decision(elimination_result: dict | None) -> dict:
    if not isinstance(elimination_result, dict):
        return {}

    decision = elimination_result.get("decision") or {}
    sales_analysis = elimination_result.get("salesAnalysis") or {}

    return {
        "status": _safe_upper(decision.get("status")),
        "action": _safe_upper(decision.get("recommendedAction")),
        "score": _safe_float(decision.get("scoreElimination"), 0.0),
        "priority": decision.get("priority"),
        "reasons": decision.get("reasons") or [],
        "next_actions": decision.get("nextActions") or [],
        "total_sales": _safe_float(sales_analysis.get("totalSales"), 0.0),
        "weekly_demand": _safe_float(sales_analysis.get("weeklyDemand"), 0.0),
        "period_days": sales_analysis.get("periodDays"),
    }


def _is_liquidation_decision(decision: dict) -> bool:
    action = decision.get("action")
    status = decision.get("status")
    score = _safe_float(decision.get("score"), 0.0)
    total_sales = _safe_float(decision.get("total_sales"), 0.0)
    weekly_demand = _safe_float(decision.get("weekly_demand"), 0.0)

    if action in LIQUIDATION_ACTIONS or status in LIQUIDATION_STATUSES:
        # Sécurité : si le produit vend encore bien,
        # on ne force pas une promotion de liquidation.
        if total_sales > 0 and weekly_demand > 1 and score < 50:
            return False
        return True

    return False


def _discount_from_elimination(decision: dict) -> float:
    action = decision.get("action")
    status = decision.get("status")
    score = _safe_float(decision.get("score"), 0.0)

    if action == "ELIMINATION_DEFINITIVE" or status == "DEAD_STOCK" or score >= 85:
        return 25.0

    if action == "ELIMINATION_PROGRESSIVE" or status == "ELIMINATION_CANDIDATE" or score >= 70:
        return 20.0

    if action == "LIQUIDATION_OR_PROMO" or status == "LIQUIDATION_CANDIDATE" or score >= 50:
        return 15.0

    return 0.0


def _compute_price_floor(req) -> float:
    """
    Prix minimum autorisé.
    On protège la marge minimale.
    """
    min_price = _safe_float(getattr(req, "min_price", None), 0.0)
    cost_price = _safe_float(getattr(req, "cost_price", None), 0.0)
    min_margin = _safe_float(getattr(req, "min_margin", None), 0.0)

    cost_margin_floor = 0.0

    if cost_price > 0:
        cost_margin_floor = cost_price * (1 + max(min_margin, 0.0))

    return round(max(min_price, cost_margin_floor), 2)


def _max_discount_allowed(current_price: float, price_floor: float) -> float:
    """
    Remise maximale possible sans descendre sous le prix plancher.
    """
    if current_price <= 0:
        return 0.0

    if price_floor <= 0:
        return 25.0

    if current_price <= price_floor:
        return 0.0

    return round(((current_price - price_floor) / current_price) * 100, 2)


def recommend_promo_service(product_id: int, db: Session) -> dict:
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)

    restock_result = recommend_restock_service(req, db)

    elimination_raw = get_elimination_recommendation_from_stock_service(
        product_id=product_id,
        observation_days=180,
        replacement_limit=0,
    )

    elimination_decision = _extract_elimination_decision(elimination_raw)

    current_price = _safe_float(getattr(req, "price", None), 0.0)
    current_stock = _safe_float(getattr(req, "stock", None), 0.0)
    threshold_max = _safe_float(getattr(req, "threshold_max", None), 0.0)

    price_floor = _compute_price_floor(req)

    max_discount_by_margin = _max_discount_allowed(
        current_price=current_price,
        price_floor=price_floor,
    )

    should_promote = False
    recommended_discount = 0.0
    reason_parts: list[str] = []
    promo_source = "NONE"

    # ==========================================================
    # 1. Promotion liée à la liquidation / élimination
    # ==========================================================
    if _is_liquidation_decision(elimination_decision):
        liquidation_discount = _discount_from_elimination(elimination_decision)

        should_promote = True
        recommended_discount = max(recommended_discount, liquidation_discount)
        promo_source = "ELIMINATION_RECOMMENDATION"

        reason_parts.append(
            "Promotion recommandée car le produit est candidat à la liquidation "
            "ou à l'élimination. L'objectif est d'écouler le stock avant suppression "
            "ou remplacement."
        )

    # ==========================================================
    # 2. Promotion liée au surstock
    # ==========================================================
    if threshold_max > 0 and current_stock >= threshold_max:
        should_promote = True
        recommended_discount = max(recommended_discount, 10.0)

        if promo_source == "NONE":
            promo_source = "OVERSTOCK"

        reason_parts.append(
            "Promotion recommandée car le stock actuel dépasse ou atteint le seuil maximum."
        )

    # ==========================================================
    # IMPORTANT :
    # On ne déclenche plus une promotion parce que le prix recommandé
    # est inférieur au prix actuel.
    #
    # Corriger un prix trop élevé = recommandation de prix.
    # Promotion = action commerciale temporaire.
    # ==========================================================

    # ==========================================================
    # 3. Blocage si risque de rupture
    # ==========================================================
    restock_urgency = str(getattr(restock_result, "urgency", "") or "").lower()

    if restock_urgency in ["high", "critical"]:
        should_promote = False
        recommended_discount = 0.0
        promo_source = "BLOCKED_BY_RESTOCK_RISK"
        reason_parts = [
            "Promotion déconseillée : le stock est faible ou le produit présente un risque de rupture."
        ]

    # ==========================================================
    # 4. Plafond général de remise
    # ==========================================================
    recommended_discount = min(max(recommended_discount, 0.0), 25.0)

    # ==========================================================
    # 5. Sécurité marge
    # ==========================================================
    if should_promote:
        if max_discount_by_margin <= 0:
            should_promote = False
            recommended_discount = 0.0
            promo_source = "BLOCKED_BY_MARGIN_FLOOR"
            reason_parts = [
                "Promotion déconseillée : le prix actuel est déjà proche ou inférieur au prix plancher."
            ]

        elif recommended_discount > max_discount_by_margin:
            recommended_discount = max_discount_by_margin
            reason_parts.append(
                f"La remise a été limitée à {recommended_discount:.2f}% pour respecter le prix plancher."
            )

    promo_price = round(current_price * (1 - recommended_discount / 100), 2)

    # Dernière sécurité anti-arrondi
    if should_promote and price_floor > 0 and promo_price < price_floor:
        promo_price = price_floor
        recommended_discount = (
            round(((current_price - promo_price) / current_price) * 100, 2)
            if current_price > 0
            else 0.0
        )

    explanation = (
        " ".join(reason_parts)
        if reason_parts
        else (
            "Aucune promotion recommandée. "
            "Une baisse de prix éventuelle doit être traitée par la recommandation de prix, "
            "pas par le module promotion."
        )
    )

    return {
        "product_id": product_id,

        # Résultat principal
        "should_promote": should_promote,
        "recommended_discount": recommended_discount,
        "promo_price": promo_price,
        "explanation": explanation,
        "promo_source": promo_source,

        # Sécurité marge
        "price_floor": price_floor,
        "max_discount_by_margin": max_discount_by_margin,

        # Données élimination
        "elimination_status": elimination_decision.get("status"),
        "elimination_action": elimination_decision.get("action"),
        "elimination_score": elimination_decision.get("score"),
        "elimination_total_sales": elimination_decision.get("total_sales"),
        "elimination_weekly_demand": elimination_decision.get("weekly_demand"),

        # Données stock
        "current_price": current_price,
        "current_stock": current_stock,
        "threshold_max": threshold_max,
        "restock_urgency": restock_urgency,

        # Compatibilité front
        "promotion_recommended": should_promote,
        "promo_recommendation": "Oui" if should_promote else "Non",
        "discount_percent": recommended_discount,
        "discount_rate": recommended_discount,
        "promotional_price": promo_price,
        "recommended_price_after_discount": promo_price,
        "reasoning": explanation,
        "message": explanation,
    }