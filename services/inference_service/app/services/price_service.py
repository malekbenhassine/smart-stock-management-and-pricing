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


def _get_current_season(target_date) -> str:
    month = target_date.month
    return {
        12: "Winter", 1: "Winter", 2: "Winter",
        3: "Spring", 4: "Spring", 5: "Spring",
        6: "Summer", 7: "Summer", 8: "Summer",
        9: "Autumn", 10: "Autumn", 11: "Autumn",
    }[month]


def _resolve_peak_season(product: dict) -> str | None:
    if product.get("peak_season"):
        return product.get("peak_season")

    if product.get("season"):
        return product.get("season")

    category = product.get("category", product.get("categorie"))
    if not category:
        return None

    cat = str(category).strip().lower()

    mapping = {
        "laptops": "Autumn",
        "desktops": "Autumn",
        "gpu": "Autumn",
        "cpu": "Autumn",
        "mémoire ram": "Autumn",
        "moniteurs": "Autumn",
        "périphériques": "AllSeason",
        "réseaux": "AllSeason",
        "stockage": "AllSeason",
        "câbles & accessoires": "AllSeason",
        "claviers & souris": "AllSeason",
    }

    return mapping.get(cat)


def _is_peak_season(peak_season: str | None, current_season: str) -> bool | None:
    if peak_season == "AllSeason":
        return True
    if peak_season:
        return peak_season == current_season
    return None


# ─────────────────────────────────────────────────────────────────────────────
# FIX: Constante MAX_PRICE_CHANGE réduite via des plafonds locaux
# On n'écrase pas la config globale mais on borne localement à ±10 %
# ─────────────────────────────────────────────────────────────────────────────
_LOCAL_MAX_CHANGE = min(MAX_PRICE_CHANGE, 0.10)   # jamais > 10 %
_MIN_REVENUE_GAIN = 0.02                           # gain réel minimum pour accepter une hausse (+2 %)


def recommend_price_service(req: BaseRequest, db: Session) -> PricingResponse:
    model, trained_features, use_log = get_model()

    current_price = float(req.price)
    current_stock = float(req.stock)
    threshold_min = float(req.threshold_min or 0.0)
    threshold_max = float(req.threshold_max or 0.0)
    min_price = float(req.min_price) if req.min_price is not None else current_price
    cost_price = float(req.cost_price) if req.cost_price is not None else 0.0

    peak_season = getattr(req, "peak_season", None)
    seasonality_factor = float(getattr(req, "seasonality_factor", 1.0) or 1.0)
    current_season = _get_current_season(req.date)
    is_peak_season = _is_peak_season(peak_season, current_season)

    safe_floor = max(min_price, cost_price)

    history_count = len(
        get_recent_history_from_stock_service(product_id=req.product_id, limit=30)
    )

    # ── Fallback : historique insuffisant ────────────────────────────────────
    if history_count < 14:
        recommended_price = current_price
        reasoning = (
            "Prix actuel conservé : historique réel insuffisant pour une recommandation fiable."
        )

        if threshold_max > 0:
            overstock_ratio = current_stock / threshold_max

            if overstock_ratio >= 1.35:
                candidate = round(current_price * 0.95, 2)
                if is_peak_season is True:
                    candidate = round(current_price * 0.97, 2)
                recommended_price = max(safe_floor, candidate)
                reasoning = (
                    "Baisse modérée recommandée : surstock important avec historique insuffisant. "
                    "Réduction prudente pour favoriser l'écoulement."
                )

            elif overstock_ratio >= 1.15:
                candidate = round(current_price * 0.98, 2)
                if is_peak_season is False:
                    candidate = round(current_price * 0.97, 2)
                recommended_price = max(safe_floor, candidate)
                reasoning = (
                    "Baisse légère recommandée : stock élevé avec historique insuffisant. "
                    "Réduction prudente pour soutenir les ventes."
                )

        if threshold_min > 0 and current_stock <= threshold_min:
            recommended_price = current_price
            if is_peak_season is True:
                candidate = round(current_price * 1.02, 2)
                recommended_price = max(safe_floor, candidate)
            reasoning = (
                "Prix actuel conservé : stock faible et historique insuffisant. "
                "Aucune baisse n'est appliquée sans données fiables."
            )

        price_change_pct = (
            round(((recommended_price - current_price) / current_price) * 100, 2)
            if current_price > 0 else 0.0
        )

        fallback_demand = float(req.units_ordered or 0.0)
        if fallback_demand <= 0:
            fallback_demand = max(1.0, round(float(req.stock) * 0.05, 1))

        return PricingResponse(
            store_id=req.store_id,
            product_id=req.product_id,
            date=req.date,
            current_price=current_price,
            recommended_price=round(recommended_price, 2),
            price_change_pct=price_change_pct,
            predicted_demand_at_current_price=fallback_demand,
            predicted_demand_at_recommended_price=fallback_demand,
            reasoning=reasoning,
        )

    # ── Bornes de la grille de prix ───────────────────────────────────────────
    # FIX 1 : utiliser _LOCAL_MAX_CHANGE (≤ 10 %) au lieu de MAX_PRICE_CHANGE brut
    min_price_ml = current_price * (1 - _LOCAL_MAX_CHANGE)
    max_price_ml = current_price * (1 + _LOCAL_MAX_CHANGE)
    min_price_ml = max(min_price_ml, safe_floor)

    # FIX 2 : le bonus peak ne gonfle plus le plafond — il joue uniquement
    #         dans le score, pas dans la grille de prix
    # (anciennement : max_price_ml *= 1.15 en peak → supprimé)

    price_grid = np.linspace(min_price_ml, max_price_ml, 21)

    # ── Demande et score de référence au prix actuel ──────────────────────────
    demand_at_current = _predict_demand_for_price(
        model, trained_features, use_log, db, req, current_price
    )

    current_margin = max(current_price - cost_price, 0.0)
    baseline_revenue = current_price * demand_at_current
    baseline_margin_value = current_margin * demand_at_current

    best_price = current_price
    best_demand = demand_at_current
    # FIX 3 : score baseline relatif (0) — on mesure le gain, pas la valeur absolue
    best_score = 0.0

    for test_price in price_grid:
        test_price = round(float(test_price), 2)

        demand = _predict_demand_for_price(
            model, trained_features, use_log, db, req, test_price
        )

        margin_per_unit = max(test_price - cost_price, 0.0)
        revenue = test_price * demand
        margin_value = margin_per_unit * demand

        # FIX 4 : pénalité d'élasticité — pénalise la chute de demande
        demand_retention = demand / demand_at_current if demand_at_current > 0 else 1.0
        elasticity_penalty = (
            max(0.0, 1.0 - demand_retention) * baseline_revenue * 0.5
        )

        season_bonus = 1.0
        if is_peak_season is True:
            season_bonus = 1.08
        elif is_peak_season is False:
            season_bonus = 0.94

        # FIX 5 : score RELATIF au baseline
        revenue_gain = revenue - baseline_revenue
        margin_gain = margin_value - baseline_margin_value

        score = (
            revenue_gain
            + (margin_gain * 0.35 * season_bonus * seasonality_factor)
            - elasticity_penalty
        )

        # FIX 6 : garde-fou — n'accepter une hausse que si le gain réel est ≥ 2 %
        if test_price > current_price:
            real_revenue_gain_pct = revenue / baseline_revenue - 1 if baseline_revenue > 0 else 0.0
            if real_revenue_gain_pct < _MIN_REVENUE_GAIN:
                continue

        if score > best_score:
            best_score = score
            best_price = test_price
            best_demand = demand

    best_price = float(round(best_price, 2))
    best_demand = float(round(best_demand, 1))
    demand_at_current = float(round(demand_at_current, 1))
    change_pct = float(round((best_price - current_price) / current_price * 100, 2))

    # ── FIX 7 : garde-fou final — si la hausse ne génère pas +2 % de CA réel,
    #    on revient au prix courant ──────────────────────────────────────────
    if best_price > current_price and baseline_revenue > 0:
        actual_revenue_gain = (best_price * best_demand) / baseline_revenue - 1
        if actual_revenue_gain < _MIN_REVENUE_GAIN:
            best_price = current_price
            best_demand = demand_at_current
            change_pct = 0.0

    # ── Génération du raisonnement ────────────────────────────────────────────
    if abs(change_pct) < 1.0:
        reasoning = "Le prix actuel est déjà proche de l'optimal."
    elif change_pct > 0:
        if is_peak_season is True:
            reasoning = (
                f"Augmenter le prix de {change_pct:.1f} % est pertinent : "
                f"le produit est en saison favorable et peut générer davantage de marge."
            )
        else:
            reasoning = (
                f"Augmenter le prix de {change_pct:.1f} % devrait améliorer "
                f"le revenu total et la rentabilité."
            )
    else:
        if is_peak_season is False:
            reasoning = (
                f"Baisser le prix de {abs(change_pct):.1f} % est pertinent : "
                f"le produit est hors saison et un ajustement peut soutenir la demande."
            )
        else:
            reasoning = (
                f"Baisser le prix de {abs(change_pct):.1f} % devrait améliorer le revenu total."
            )

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

    raw_cost_price = product.get("cost_price", product.get("prixCout", 0.0))
    raw_min_margin = product.get("min_margin", product.get("margeReservee", 0.0))

    cost_price = float(raw_cost_price or 0.0)
    min_margin = float(raw_min_margin or 0.0) / 100.0

    peak_season = _resolve_peak_season(product)
    season = _get_current_season(result.date)
    is_peak_season = _is_peak_season(peak_season, season)

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

    current_margin_per_unit = max(current_price - cost_price, 0.0)
    recommended_margin_per_unit = max(final_recommended_price - cost_price, 0.0)

    current_margin_week = current_margin_per_unit * predicted_current
    recommended_margin_week = recommended_margin_per_unit * predicted_recommended

    estimated_margin_impact_week = round(
        recommended_margin_week - current_margin_week, 2
    )

    explanation = build_price_explanation(
        current_price=current_price,
        recommended_price=final_recommended_price,
        predicted_demand=predicted_recommended,
        price_direction=direction,
        current_demand=predicted_current,
        season=season,
        is_peak_season=is_peak_season,
    )

    return {
        "product_id": result.product_id,
        "recommended_price": final_recommended_price,
        "price_change_pct": round(((final_recommended_price - current_price) / current_price) * 100, 2)
        if current_price > 0 else 0.0,
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
        "season": season,
        "peak_season": peak_season,
        "is_peak_season": is_peak_season,
        "explanation": explanation,
    }