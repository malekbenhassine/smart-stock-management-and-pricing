from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

import requests

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.tables import (
    Product,
    SalesHistory,
    ProductPromotion,
    Promotion,
    Sale,
    SaleLine,
    StockMovement,
)


# -----------------------------------------------------------------------------
# Règles métier utilisées dans le marché tunisien / retail IT
# -----------------------------------------------------------------------------
WATCH_DAYS = 30          # aucune vente => surveillance
DORMANT_DAYS = 60        # aucune vente => produit dormant
LIQUIDATION_DAYS = 90    # aucune vente => liquidation / promo forte
ELIMINATION_DAYS = 180   # aucune vente => candidat élimination progressive
DEAD_STOCK_DAYS = 365    # aucune vente => stock mort

DEFAULT_MIN_WEEKLY_DEMAND = 1.0
DEFAULT_REPLACEMENT_LIMIT = 3

# -----------------------------------------------------------------------------
# Intégration optionnelle avec inference_service
# -----------------------------------------------------------------------------
# Objectif : la recommandation d’élimination ne doit pas se baser uniquement
# sur la moyenne historique longue. Si le modèle ML prévoit encore une demande
# positive sur 7 jours, le produit doit être protégé contre une élimination.
#
# Dans Docker : http://inference_service:8020
# En local : http://localhost:8020
INFERENCE_SERVICE_URL = os.getenv("INFERENCE_SERVICE_URL", "http://inference_service:8020").rstrip("/")
INFERENCE_SERVICE_PUBLIC_URL = os.getenv("INFERENCE_SERVICE_PUBLIC_URL", "http://localhost:8020").rstrip("/")
ELIMINATION_USE_ML_DEMAND = os.getenv("ELIMINATION_USE_ML_DEMAND", "true").lower() in {"1", "true", "yes", "on"}
ELIMINATION_USE_ML_IN_LIST = os.getenv("ELIMINATION_USE_ML_IN_LIST", "false").lower() in {"1", "true", "yes", "on"}
ELIMINATION_ML_TIMEOUT_SECONDS = int(os.getenv("ELIMINATION_ML_TIMEOUT_SECONDS", "8"))


STOP_WORDS = {
    "de", "du", "des", "le", "la", "les", "un", "une", "et", "avec", "sans",
    "pour", "dans", "sur", "en", "au", "aux", "a", "à", "the", "and", "or",
    "go", "gb", "ram", "rom", "noir", "blanc", "bleu", "rouge", "gris", "silver",
    "black", "white", "blue", "red", "green", "gold", "rose", "new", "nouveau",
}

SEASONAL_KEYWORDS = {
    "ramadan", "aid", "aïd", "rentrée", "scolaire", "été", "hiver", "climatiseur",
    "chauffage", "cartable", "fourniture", "maillot", "ventilateur", "soldes",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _round(value: Any, digits: int = 2):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except Exception:
        return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower()
    text = text.replace("é", "e").replace("è", "e").replace("ê", "e")
    text = text.replace("à", "a").replace("â", "a")
    text = text.replace("î", "i").replace("ï", "i")
    text = text.replace("ô", "o")
    text = text.replace("ù", "u").replace("û", "u")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(*values: Any) -> set[str]:
    text = _normalize_text(" ".join(str(v or "") for v in values))
    return {
        token
        for token in text.split()
        if len(token) >= 2 and token not in STOP_WORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _text_similarity(a: str, b: str) -> float:
    a = _normalize_text(a)
    b = _normalize_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _normalize_margin(value: Any) -> float:
    margin = _safe_float(value, 0.2)
    if margin > 1:
        margin = margin / 100
    if margin < 0:
        margin = 0.2
    return margin


def _price_floor(product: Product) -> float | None:
    cost = _safe_float(product.prix_cout, 0)
    if cost <= 0:
        return None
    margin = _normalize_margin(product.marge_reservee)
    return round(cost * (1 + margin), 2)


def _margin_rate(product: Product) -> float | None:
    price = _safe_float(product.prix_vente, 0)
    cost = _safe_float(product.prix_cout, 0)
    if price <= 0 or cost <= 0:
        return None
    return round((price - cost) / price, 4)


def _serialize_product(product: Product) -> dict:
    return {
        "id": product.id,
        "sku": product.sku,
        "nom": product.nom,
        "categorie": product.categorie,
        "marque": product.marque,
        "description": product.description,
        "prixVente": product.prix_vente,
        "prixCout": product.prix_cout,
        "margeReservee": product.marge_reservee,
        "stockDisponible": product.stock_disponible,
        "stockReserve": product.stock_reserve,
        "stockMinimum": product.stock_minimum,
        "seuilMin": product.seuil_min,
        "seuilMax": product.seuil_max,
        "statut": product.statut,
    }


def _analysis_anchor_date(db: Session) -> date:
    """
    Date d'ancrage de l'analyse.

    ANCIENNE LOGIQUE : uniquement historique_ventes.
    NOUVELLE LOGIQUE : on ancre sur la date la plus récente disponible dans :
    - historique_ventes ;
    - ventes + lignes_ventes ;
    - mouvement_stock.

    Cela évite de considérer un produit comme sans vente simplement parce que
    les ventes récentes sont dans les tables métier et non dans le CSV ML.
    """
    dates: list[date] = []

    max_history_date = db.query(func.max(SalesHistory.date)).scalar()
    if max_history_date:
        dates.append(max_history_date)

    max_sale_date = db.query(func.max(func.date(Sale.date_vente))).scalar()
    if max_sale_date:
        dates.append(max_sale_date)

    max_movement_date = db.query(func.max(func.date(StockMovement.date_mouvement))).scalar()
    if max_movement_date:
        dates.append(max_movement_date)

    if dates:
        return max(dates)

    return date.today()



def _extract_weekly_demand_from_restock_response(data: dict) -> float | None:
    """
    Extrait une demande prévue sur 7 jours depuis la réponse /recommend/restock/{id}.

    Priorité :
    1. safe_weekly_demand / retained_weekly_demand : valeur sécurisée par garde-fou ;
    2. predicted_demand_7d / predicted_demand / weekly_demand : prévision ML ;
    3. estimated_impact.forecast_p50_lead_time : ancienne réponse compatible.
    """
    if not isinstance(data, dict):
        return None

    candidates = [
        data.get("safe_weekly_demand"),
        data.get("retained_weekly_demand"),
        data.get("predicted_demand_7d"),
        data.get("predicted_demand"),
        data.get("weekly_demand"),
    ]

    estimated = data.get("estimated_impact") or {}
    if isinstance(estimated, dict):
        candidates.extend([
            estimated.get("forecast_p50_lead_time"),
            estimated.get("forecast_p50"),
        ])

    for value in candidates:
        val = _safe_float(value, -1)
        if val >= 0:
            return val

    return None


def _fetch_ml_demand_forecast(product_id: int) -> dict:
    """
    Appelle inference_service pour récupérer la demande prévue sur 7 jours.

    Cette fonction est volontairement tolérante : si inference_service est arrêté,
    si la route n’existe pas ou si la réponse est invalide, on ne bloque jamais
    la recommandation d’élimination. On revient simplement à la demande historique.
    """
    if not ELIMINATION_USE_ML_DEMAND:
        return {
            "enabled": False,
            "status": "DISABLED",
            "weeklyDemand": None,
            "source": "disabled",
            "error": None,
            "raw": None,
        }

    urls = [
        f"{INFERENCE_SERVICE_URL}/recommend/restock/{product_id}",
        f"{INFERENCE_SERVICE_PUBLIC_URL}/recommend/restock/{product_id}",
    ]

    last_error = None
    for url in urls:
        try:
            response = requests.get(url, timeout=ELIMINATION_ML_TIMEOUT_SECONDS)
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                continue

            data = response.json()
            weekly = _extract_weekly_demand_from_restock_response(data)

            if weekly is None:
                return {
                    "enabled": True,
                    "status": "NO_WEEKLY_VALUE",
                    "weeklyDemand": None,
                    "source": url,
                    "error": "Aucune valeur de demande hebdomadaire trouvée dans la réponse ML.",
                    "raw": data,
                }

            return {
                "enabled": True,
                "status": "OK",
                "weeklyDemand": round(float(weekly), 2),
                "mlWeeklyDemand": _round(data.get("ml_weekly_demand")),
                "safeWeeklyDemand": _round(data.get("safe_weekly_demand")),
                "recentSales7d": _round(data.get("recent_sales_7d")),
                "observedWeekly30d": _round(data.get("observed_weekly_30d")),
                "guardrailLabel": data.get("forecast_guardrail_label"),
                "guardrailStatus": data.get("forecast_guardrail_status"),
                "source": url,
                "error": None,
                "raw": data,
            }
        except Exception as exc:
            last_error = str(exc)
            continue

    return {
        "enabled": True,
        "status": "ERROR",
        "weeklyDemand": None,
        "source": None,
        "error": last_error,
        "raw": None,
    }


def _merge_ml_demand_into_stats(stats: dict, ml_forecast: dict | None) -> dict:
    """
    Ajoute la prévision ML aux statistiques d’élimination.

    Logique métier : pour l’élimination, on protège le produit si une source de
    demande indique une demande positive. On utilise donc :

        demande retenue = max(demande historique, demande ML 7 jours)

    Cela évite d’éliminer un produit dont l’historique long semble moyen/faible
    mais dont le modèle prévoit encore une demande court terme.
    """
    stats = dict(stats or {})
    historical_weekly = _safe_float(stats.get("weekly_demand"), 0)
    ml_weekly = None

    if ml_forecast and ml_forecast.get("weeklyDemand") is not None:
        ml_weekly = _safe_float(ml_forecast.get("weeklyDemand"), 0)

    effective_weekly = max(historical_weekly, ml_weekly or 0)

    stats["historical_weekly_demand"] = historical_weekly
    stats["ml_weekly_demand"] = ml_weekly
    stats["weekly_demand"] = effective_weekly
    stats["effective_weekly_demand"] = effective_weekly
    stats["demand_source"] = (
        "ML_AND_HISTORY_MAX"
        if ml_weekly is not None and ml_weekly > historical_weekly
        else "HISTORY"
    )
    stats["ml_forecast"] = ml_forecast or {
        "enabled": ELIMINATION_USE_ML_DEMAND,
        "status": "NOT_CALLED",
        "weeklyDemand": None,
        "error": None,
    }

    return stats


def _sales_stats_for_sku(db: Session, sku: str | None, anchor_date: date, days: int) -> dict:
    """
    Calcule les ventes utilisées par la recommandation d'élimination.

    ANCIENNE LOGIQUE :
    - lisait uniquement SalesHistory.product_id == sku.

    NOUVELLE LOGIQUE :
    - SalesHistory par SKU ;
    - ventes + lignes_ventes par produit_id ;
    - mouvement_stock seulement si SORTIE + VENTE_CLIENT / COMMANDE_CLIENT_LIVREE.

    Important : les mouvements stock ne sont ajoutés comme ventes que si aucune
    ligne de vente n'existe déjà sur la période, pour éviter un double comptage.
    """
    period_start = anchor_date - timedelta(days=days - 1)

    empty_result = {
        "period_days": days,
        "period_start": period_start,
        "period_end": anchor_date,
        "rows_count": 0,
        "total_sales": 0.0,
        "avg_daily_sales": 0.0,
        "weekly_demand": 0.0,
        "last_sale_date": None,
        "days_since_last_sale": None,
        "has_discount_signal": False,
    }

    if not sku:
        return empty_result

    product = db.query(Product).filter(Product.sku == sku).first()
    numeric_product_id = product.id if product else None

    rows_count = 0
    total_sales = 0.0
    last_sale_dates: list[date] = []
    has_discount_signal = False

    # ------------------------------------------------------------------
    # Source 1 : historique_ventes / SalesHistory.
    # ------------------------------------------------------------------
    history_rows = (
        db.query(SalesHistory)
        .filter(SalesHistory.product_id == sku)
        .filter(SalesHistory.date >= period_start)
        .filter(SalesHistory.date <= anchor_date)
        .all()
    )

    rows_count += len(history_rows)
    total_sales += sum(_safe_float(row.sales, 0) for row in history_rows)
    has_discount_signal = any(_safe_float(row.discount, 0) > 0 for row in history_rows)

    history_last_sale = (
        db.query(func.max(SalesHistory.date))
        .filter(SalesHistory.product_id == sku)
        .filter(SalesHistory.sales > 0)
        .scalar()
    )
    if history_last_sale:
        last_sale_dates.append(history_last_sale)

    # ------------------------------------------------------------------
    # Source 2 : ventes + lignes_ventes.
    # ------------------------------------------------------------------
    sale_rows_count = 0

    if numeric_product_id is not None:
        sale_stats = (
            db.query(
                func.count(SaleLine.id),
                func.coalesce(func.sum(SaleLine.quantite), 0),
                func.max(func.date(Sale.date_vente)),
            )
            .join(Sale, Sale.id == SaleLine.vente_id)
            .filter(SaleLine.produit_id == numeric_product_id)
            .filter(func.date(Sale.date_vente) >= period_start)
            .filter(func.date(Sale.date_vente) <= anchor_date)
            .first()
        )

        if sale_stats:
            sale_rows_count, sale_qty, sale_last_date = sale_stats
            sale_rows_count = int(sale_rows_count or 0)
            rows_count += sale_rows_count
            total_sales += _safe_float(sale_qty, 0)

            if sale_last_date:
                last_sale_dates.append(sale_last_date)

        # ------------------------------------------------------------------
        # Source 3 : mouvement_stock.
        # Seulement les sorties réellement liées à une vente client.
        # ------------------------------------------------------------------
        movement_stats = (
            db.query(
                func.count(StockMovement.id),
                func.coalesce(func.sum(StockMovement.quantite), 0),
                func.max(func.date(StockMovement.date_mouvement)),
            )
            .filter(StockMovement.produit_id == numeric_product_id)
            .filter(func.upper(StockMovement.type) == "SORTIE")
            .filter(
                func.upper(StockMovement.justification).in_(
                    ["VENTE_CLIENT", "COMMANDE_CLIENT_LIVREE"]
                )
            )
            .filter(func.date(StockMovement.date_mouvement) >= period_start)
            .filter(func.date(StockMovement.date_mouvement) <= anchor_date)
            .first()
        )

        if movement_stats:
            movement_rows_count, movement_qty, movement_last_date = movement_stats
            movement_rows_count = int(movement_rows_count or 0)

            # Évite le double comptage : si des lignes de vente existent déjà
            # pour ce produit sur la période, elles sont la source principale.
            if sale_rows_count == 0:
                rows_count += movement_rows_count
                total_sales += _safe_float(movement_qty, 0)

            if movement_last_date:
                last_sale_dates.append(movement_last_date)

    avg_daily_sales = total_sales / days if days > 0 else 0.0
    weekly_demand = avg_daily_sales * 7
    last_sale_date = max(last_sale_dates) if last_sale_dates else None

    if last_sale_date:
        days_since_last_sale = max(0, (anchor_date - last_sale_date).days)
    else:
        days_since_last_sale = None

    return {
        "period_days": days,
        "period_start": period_start,
        "period_end": anchor_date,
        "rows_count": rows_count,
        "total_sales": total_sales,
        "avg_daily_sales": avg_daily_sales,
        "weekly_demand": weekly_demand,
        "last_sale_date": last_sale_date,
        "days_since_last_sale": days_since_last_sale,
        "has_discount_signal": has_discount_signal,
    }

def _has_active_promotion(db: Session, product_id: int, anchor_date: date) -> bool:
    active = (
        db.query(ProductPromotion)
        .join(Promotion, Promotion.id == ProductPromotion.promotion_id)
        .filter(ProductPromotion.produit_id == product_id)
        .filter(Promotion.actif == True)  # noqa: E712
        .filter((Promotion.date_debut == None) | (Promotion.date_debut <= anchor_date))  # noqa: E711
        .filter((Promotion.date_fin == None) | (Promotion.date_fin >= anchor_date))      # noqa: E711
        .first()
    )
    return active is not None


def _is_seasonal_product(product: Product) -> bool:
    toks = _tokens(product.nom, product.categorie, product.description)
    return bool(toks & SEASONAL_KEYWORDS)


def _price_position_score(product: Product) -> tuple[int, str]:
    """
    Sans prix concurrents ici, on évalue seulement le risque interne :
    prix trop proche ou inférieur au prix plancher = risque de rentabilité.
    """
    price = _safe_float(product.prix_vente, 0)
    floor = _price_floor(product)

    if price <= 0 or floor is None:
        return 5, "Prix ou prix de revient incomplet."

    if price < floor:
        return 10, "Le prix actuel est inférieur au prix plancher coût + marge."

    if price <= floor * 1.05:
        return 5, "Le prix actuel est très proche du prix plancher."

    return 0, "La marge minimale semble respectée."


def _compute_elimination_decision(
    product: Product,
    stats: dict,
    anchor_date: date,
    observation_days: int,
    min_weekly_demand: float,
    promotion_tested: bool,
) -> dict:
    """
    Décision prudente :
    - Un produit qui vend encore beaucoup ne doit JAMAIS être classé liquidation/élimination.
    - La liquidation/élimination est réservée aux produits sans vente ou avec demande très faible.
    - Les seuils d'inactivité servent à prioriser, mais ils ne doivent pas écraser le score.
    """
    stock = _safe_int(product.stock_disponible, 0)
    seuil_max = _safe_int(product.seuil_max, 0)
    weekly_demand = _safe_float(stats.get("weekly_demand"), 0)
    historical_weekly_demand = _safe_float(stats.get("historical_weekly_demand", weekly_demand), 0)
    ml_weekly_demand = stats.get("ml_weekly_demand")
    demand_source = stats.get("demand_source", "HISTORY")
    total_sales = _safe_float(stats.get("total_sales"), 0)
    days_since_last_sale = stats.get("days_since_last_sale")

    if days_since_last_sale is None:
        inactivity_days = observation_days if total_sales <= 0 else 0
    else:
        inactivity_days = _safe_int(days_since_last_sale, 0)

    is_seasonal = _is_seasonal_product(product)
    price_points, price_reason = _price_position_score(product)

    score = 0
    reasons: list[str] = []
    next_actions: list[str] = []

    has_positive_sales = total_sales > 0
    has_healthy_demand = weekly_demand > min_weekly_demand
    has_strong_sales = total_sales >= max(5, min_weekly_demand * (observation_days / 7))

    # ------------------------------------------------------------------
    # GARDE-FOU ABSOLU
    # Un produit qui vend encore sur la période observée ET qui a une
    # demande hebdomadaire supérieure au seuil ne peut jamais être classé
    # comme LIQUIDATION_CANDIDATE, même s'il a du stock ou une promo.
    # ------------------------------------------------------------------
    if has_positive_sales and has_healthy_demand:
        reasons = [
            f"Le produit a encore vendu {round(total_sales, 2)} unité(s) sur la période analysée : il ne doit pas être liquidé.",
            f"Demande hebdomadaire retenue : {round(weekly_demand, 2)} unité(s)/semaine.",
            f"Stock disponible : {stock} unité(s).",
            price_reason,
        ]

        if demand_source == "ML_AND_HISTORY_MAX" and ml_weekly_demand is not None:
            reasons.append(
                f"La prévision ML court terme ({round(_safe_float(ml_weekly_demand), 2)} unité(s)/7 jours) "
                f"est supérieure à la moyenne historique ({round(historical_weekly_demand, 2)} unité(s)/semaine) : "
                "le produit doit être conservé."
            )

        if promotion_tested:
            reasons.append("Une promotion/remise existe, mais le produit vend encore : ce n'est pas un motif d'élimination.")

        return {
            "status": "KEEP",
            "recommendedAction": "GARDER",
            "priority": "none",
            "scoreElimination": 0,
            "shouldRecommendElimination": False,
            "isSeasonalProduct": is_seasonal,
            "promotionTested": promotion_tested,
            "inactivityDays": inactivity_days,
            "rules": {
                "watchDays": WATCH_DAYS,
                "dormantDays": DORMANT_DAYS,
                "liquidationDays": LIQUIDATION_DAYS,
                "eliminationDays": ELIMINATION_DAYS,
                "deadStockDays": DEAD_STOCK_DAYS,
                "minWeeklyDemand": min_weekly_demand,
                "marketContext": "Règles prudentes adaptées au retail tunisien : un produit avec ventes positives et demande saine est conservé.",
            },
            "reasons": reasons,
            "nextActions": [
                "Aucune liquidation recommandée.",
                "Aucune élimination recommandée.",
                "Continuer le suivi normal du stock, du prix et de la demande.",
            ],
            "explanation": _build_elimination_explanation(product, "KEEP", "GARDER", 0, reasons),
        }

    if stock <= 0:
        score -= 25
        reasons.append("Stock nul : pas d'immobilisation de stock à liquider.")
    else:
        reasons.append(f"Stock disponible positif : {stock} unité(s).")

    # 1) Ventes observées : critère le plus important.
    if has_positive_sales:
        if has_strong_sales or has_healthy_demand:
            score -= 35
            reasons.append(
                f"Le produit a encore vendu {round(total_sales, 2)} unité(s) sur la période analysée : il ne doit pas être liquidé."
            )
        else:
            score -= 10
            reasons.append(f"Le produit a encore quelques ventes : {round(total_sales, 2)} unité(s) sur la période analysée.")
    else:
        if inactivity_days >= DEAD_STOCK_DAYS:
            score += 55
            reasons.append("Aucune vente depuis au moins 365 jours : stock mort probable.")
        elif inactivity_days >= ELIMINATION_DAYS:
            score += 45
            reasons.append("Aucune vente depuis au moins 180 jours : candidat à l'élimination progressive.")
        elif inactivity_days >= LIQUIDATION_DAYS:
            score += 30
            reasons.append("Aucune vente depuis au moins 90 jours : liquidation recommandée avant élimination.")
        elif inactivity_days >= DORMANT_DAYS:
            score += 18
            reasons.append("Aucune vente depuis au moins 60 jours : produit dormant à surveiller.")
        elif inactivity_days >= WATCH_DAYS:
            score += 10
            reasons.append("Aucune vente depuis au moins 30 jours : surveillance recommandée.")
        else:
            score += 5
            reasons.append("Aucune vente sur la période, mais la durée reste courte.")

    # 2) Demande hebdomadaire : si elle est positive, on protège le produit.
    if weekly_demand <= 0:
        score += 15
        reasons.append("Demande hebdomadaire retenue estimée nulle.")
    elif weekly_demand <= min_weekly_demand:
        score += 10
        reasons.append(f"Demande hebdomadaire retenue faible : {round(weekly_demand, 2)} unité(s)/semaine.")
    else:
        score -= 25
        reasons.append(f"Demande hebdomadaire retenue encore positive : {round(weekly_demand, 2)} unité(s)/semaine.")

    if demand_source == "ML_AND_HISTORY_MAX" and ml_weekly_demand is not None:
        reasons.append(
            f"La demande retenue utilise la prévision ML : {round(_safe_float(ml_weekly_demand), 2)} unité(s)/7 jours, "
            f"contre {round(historical_weekly_demand, 2)} unité(s)/semaine en moyenne historique."
        )

    # 3) Surstock : seulement un risque de liquidation si la demande est faible.
    if seuil_max > 0 and stock >= seuil_max:
        if has_healthy_demand:
            score += 3
            reasons.append("Stock élevé, mais la demande reste positive : surveillance plutôt que liquidation.")
        else:
            score += 12
            reasons.append("Le stock est supérieur ou égal au seuil maximum : risque de surstockage.")
    elif seuil_max > 0 and stock >= seuil_max * 0.75:
        if has_healthy_demand:
            reasons.append("Stock proche du seuil maximum, mais les ventes restent actives.")
        else:
            score += 6
            reasons.append("Le stock est proche du seuil maximum.")

    score += price_points
    reasons.append(price_reason)

    # 4) Une promo déjà testée n'est un signal négatif que si elle n'a PAS généré de ventes.
    if promotion_tested and not has_positive_sales:
        score += 8
        reasons.append("Une promotion ou remise a déjà été testée sans générer de vente sur la période.")
    elif promotion_tested and has_positive_sales:
        reasons.append("Une promotion/remise existe, mais le produit vend encore : ce n'est pas un motif d'élimination.")
    else:
        reasons.append("Aucune promotion testée n'est détectée : tenter une action commerciale seulement si les ventes deviennent faibles.")

    if is_seasonal:
        score -= 20
        reasons.append("Produit potentiellement saisonnier : éviter l'élimination hors saison sans validation humaine.")

    score = max(0, min(100, int(round(score))))

    # Blocage métier important : avec ventes positives et demande saine, on garde le produit.
    if has_positive_sales and has_healthy_demand and score < 50:
        status = "KEEP"
        action = "GARDER"
        priority = "none"
        next_actions = [
            "Aucune élimination recommandée.",
            "Continuer le suivi normal du stock et du prix.",
            "Éviter de proposer des remplaçants tant que le produit se vend correctement.",
        ]
    elif score >= 85 or (not has_positive_sales and inactivity_days >= DEAD_STOCK_DAYS and stock > 0):
        status = "DEAD_STOCK"
        action = "ELIMINATION_DEFINITIVE"
        priority = "critical"
        next_actions = [
            "Bloquer le réapprovisionnement.",
            "Liquider le stock restant ou négocier un retour fournisseur.",
            "Remplacer le produit par les alternatives recommandées.",
        ]
    elif score >= 70 or (
        not has_positive_sales
        and inactivity_days >= ELIMINATION_DAYS
        and stock > 0
        and weekly_demand <= min_weekly_demand
    ):
        status = "ELIMINATION_CANDIDATE"
        action = "ELIMINATION_PROGRESSIVE"
        priority = "high"
        next_actions = [
            "Ne plus recommander de réapprovisionnement.",
            "Lancer une liquidation contrôlée.",
            "Mettre en avant les produits remplaçants.",
        ]
    elif score >= 50 or (
        not has_positive_sales
        and inactivity_days >= LIQUIDATION_DAYS
        and stock > 0
        and weekly_demand <= min_weekly_demand
    ):
        status = "LIQUIDATION_CANDIDATE"
        action = "LIQUIDATION_OR_PROMO"
        priority = "medium"
        next_actions = [
            "Appliquer une promotion limitée.",
            "Comparer le prix avec le marché.",
            "Réévaluer après la période de promotion.",
        ]
    elif score >= 30 or (not has_positive_sales and inactivity_days >= DORMANT_DAYS):
        status = "DORMANT"
        action = "SURVEILLER"
        priority = "low"
        next_actions = [
            "Surveiller les ventes.",
            "Vérifier la fiche produit et la visibilité.",
            "Analyser le positionnement prix.",
        ]
    else:
        status = "KEEP"
        action = "GARDER"
        priority = "none"
        next_actions = ["Aucune élimination recommandée pour le moment."]

    should_recommend_elimination = action in {"ELIMINATION_PROGRESSIVE", "ELIMINATION_DEFINITIVE"}

    return {
        "status": status,
        "recommendedAction": action,
        "priority": priority,
        "scoreElimination": score,
        "shouldRecommendElimination": should_recommend_elimination,
        "isSeasonalProduct": is_seasonal,
        "promotionTested": promotion_tested,
        "inactivityDays": inactivity_days,
        "rules": {
            "watchDays": WATCH_DAYS,
            "dormantDays": DORMANT_DAYS,
            "liquidationDays": LIQUIDATION_DAYS,
            "eliminationDays": ELIMINATION_DAYS,
            "deadStockDays": DEAD_STOCK_DAYS,
            "minWeeklyDemand": min_weekly_demand,
            "marketContext": "Règles prudentes adaptées au retail tunisien : surveiller, liquider, puis éliminer seulement après absence prolongée de ventes et demande faible.",
        },
        "reasons": reasons,
        "nextActions": next_actions,
        "explanation": _build_elimination_explanation(product, status, action, score, reasons),
    }

def _build_elimination_explanation(product: Product, status: str, action: str, score: int, reasons: list[str]) -> str:
    product_name = product.nom or f"Produit {product.id}"
    if action == "ELIMINATION_DEFINITIVE":
        intro = f"{product_name} est fortement recommandé à l'élimination définitive."
    elif action == "ELIMINATION_PROGRESSIVE":
        intro = f"{product_name} est candidat à une élimination progressive."
    elif action == "LIQUIDATION_OR_PROMO":
        intro = f"{product_name} doit d'abord être liquidé ou mis en promotion avant une suppression."
    elif action == "SURVEILLER":
        intro = f"{product_name} est à surveiller, mais l'élimination n'est pas encore recommandée."
    else:
        intro = f"{product_name} doit être conservé pour le moment."

    return f"{intro} Score d'élimination : {score}/100. Raisons principales : " + " ".join(reasons[:4])


def _candidate_similarity_score(source: Product, candidate: Product) -> tuple[int, dict]:
    source_tokens = _tokens(source.nom, source.categorie, source.marque, source.description)
    candidate_tokens = _tokens(candidate.nom, candidate.categorie, candidate.marque, candidate.description)

    token_score = _jaccard(source_tokens, candidate_tokens) * 35
    name_score = _text_similarity(source.nom or "", candidate.nom or "") * 20

    same_category = bool(source.categorie and candidate.categorie and _normalize_text(source.categorie) == _normalize_text(candidate.categorie))
    same_brand = bool(source.marque and candidate.marque and _normalize_text(source.marque) == _normalize_text(candidate.marque))

    category_score = 20 if same_category else 0
    brand_score = 10 if same_brand else 0

    source_price = _safe_float(source.prix_vente, 0)
    candidate_price = _safe_float(candidate.prix_vente, 0)
    price_score = 0
    price_gap_pct = None

    if source_price > 0 and candidate_price > 0:
        price_gap_pct = abs(candidate_price - source_price) / source_price * 100
        if price_gap_pct <= 15:
            price_score = 15
        elif price_gap_pct <= 30:
            price_score = 8
        elif price_gap_pct <= 50:
            price_score = 4

    total = int(round(token_score + name_score + category_score + brand_score + price_score))
    total = max(0, min(100, total))

    return total, {
        "tokenSimilarity": round(token_score, 2),
        "nameSimilarity": round(name_score, 2),
        "sameCategory": same_category,
        "sameBrand": same_brand,
        "priceGapPct": _round(price_gap_pct),
    }


def _replacement_score(source: Product, candidate: Product, candidate_stats: dict, similarity_score: int) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    score += int(similarity_score * 0.45)
    if similarity_score >= 70:
        reasons.append("Produit très similaire au produit à éliminer.")
    elif similarity_score >= 50:
        reasons.append("Produit similaire et utilisable comme alternative.")
    else:
        reasons.append("Similarité moyenne : alternative à vérifier manuellement.")

    stock = _safe_int(candidate.stock_disponible, 0)
    seuil_min = _safe_int(candidate.seuil_min if candidate.seuil_min is not None else candidate.stock_minimum, 0)
    weekly_demand = _safe_float(candidate_stats.get("weekly_demand"), 0)
    total_sales = _safe_float(candidate_stats.get("total_sales"), 0)

    if stock > max(0, seuil_min):
        score += 15
        reasons.append("Stock disponible suffisant.")
    elif stock > 0:
        score += 8
        reasons.append("Stock disponible, mais proche du seuil minimum.")
    else:
        score -= 20
        reasons.append("Produit remplaçant en rupture : à éviter comme remplacement immédiat.")

    if total_sales > 0:
        score += 15
        reasons.append(f"Ventes positives sur la période : {round(total_sales, 2)} unité(s).")

    if weekly_demand > DEFAULT_MIN_WEEKLY_DEMAND:
        score += 15
        reasons.append(f"Demande prévue positive : {round(weekly_demand, 2)} unité(s)/semaine.")
    elif weekly_demand > 0:
        score += 8
        reasons.append("Demande faible mais non nulle.")

    margin = _margin_rate(candidate)
    if margin is not None and margin >= 0.15:
        score += 10
        reasons.append(f"Marge correcte estimée : {round(margin * 100, 2)}%.")
    elif margin is not None and margin > 0:
        score += 4
        reasons.append("Marge positive mais faible.")

    statut = _normalize_text(candidate.statut)
    if statut and statut not in {"actif", "active", "prix valide", "prix_valide"}:
        score -= 10
        reasons.append(f"Statut produit à vérifier : {candidate.statut}.")

    score = max(0, min(100, int(round(score))))
    return score, reasons


def _find_replacements(
    product: Product,
    db: Session,
    anchor_date: date,
    period_days: int,
    limit: int,
) -> list[dict]:
    query = db.query(Product).filter(Product.id != product.id)

    # Priorité : même catégorie. Si la catégorie est absente, on analyse tout mais le score filtrera.
    if product.categorie:
        query = query.filter(Product.categorie == product.categorie)

    candidates = query.limit(250).all()
    replacements = []

    for candidate in candidates:
        similarity_score, similarity_details = _candidate_similarity_score(product, candidate)
        if similarity_score < 35:
            continue

        candidate_stats = _sales_stats_for_sku(
            db=db,
            sku=candidate.sku,
            anchor_date=anchor_date,
            days=period_days,
        )
        score, reasons = _replacement_score(product, candidate, candidate_stats, similarity_score)

        if score < 40:
            continue

        replacements.append({
            "product": _serialize_product(candidate),
            "scoreRemplacement": score,
            "similarityScore": similarity_score,
            "similarityDetails": similarity_details,
            "sales": {
                "periodDays": candidate_stats["period_days"],
                "totalSales": _round(candidate_stats["total_sales"]),
                "weeklyDemand": _round(candidate_stats["weekly_demand"]),
                "lastSaleDate": str(candidate_stats["last_sale_date"]) if candidate_stats["last_sale_date"] else None,
            },
            "marginRate": _round(_margin_rate(candidate)),
            "priceFloor": _price_floor(candidate),
            "reasons": reasons,
        })

    replacements.sort(
        key=lambda item: (
            item["scoreRemplacement"],
            item["similarityScore"],
            item["sales"]["weeklyDemand"] or 0,
        ),
        reverse=True,
    )

    return replacements[:limit]


def get_product_elimination_recommendation_service(
    product_id: int,
    db: Session,
    observation_days: int = ELIMINATION_DAYS,
    min_weekly_demand: float = DEFAULT_MIN_WEEKLY_DEMAND,
    replacement_limit: int = DEFAULT_REPLACEMENT_LIMIT,
) -> dict:
    if observation_days < 30:
        raise HTTPException(status_code=400, detail="observation_days doit être >= 30")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    anchor_date = _analysis_anchor_date(db)
    stats = _sales_stats_for_sku(db, product.sku, anchor_date, observation_days)
    ml_forecast = _fetch_ml_demand_forecast(product.id)
    stats = _merge_ml_demand_into_stats(stats, ml_forecast)
    promotion_tested = bool(stats.get("has_discount_signal")) or _has_active_promotion(db, product.id, anchor_date)

    decision = _compute_elimination_decision(
        product=product,
        stats=stats,
        anchor_date=anchor_date,
        observation_days=observation_days,
        min_weekly_demand=min_weekly_demand,
        promotion_tested=promotion_tested,
    )

    replacements = []
    if decision["recommendedAction"] in {
        "LIQUIDATION_OR_PROMO",
        "ELIMINATION_PROGRESSIVE",
        "ELIMINATION_DEFINITIVE",
    }:
        replacements = _find_replacements(
            product=product,
            db=db,
            anchor_date=anchor_date,
            period_days=min(90, observation_days),
            limit=replacement_limit,
        )

    return {
        "status": "success",
        "type": "PRODUCT_ELIMINATION_RECOMMENDATION",
        "generatedAt": datetime.utcnow().isoformat(),
        "analysisAnchorDate": str(anchor_date),
        "product": _serialize_product(product),
        "salesAnalysis": {
            "periodDays": stats["period_days"],
            "periodStart": str(stats["period_start"]),
            "periodEnd": str(stats["period_end"]),
            "rowsCount": stats["rows_count"],
            "totalSales": _round(stats["total_sales"]),
            "avgDailySales": _round(stats["avg_daily_sales"]),
            "weeklyDemand": _round(stats["weekly_demand"]),
            "historicalWeeklyDemand": _round(stats.get("historical_weekly_demand")),
            "mlWeeklyDemand": _round(stats.get("ml_weekly_demand")),
            "effectiveWeeklyDemand": _round(stats.get("effective_weekly_demand")),
            "demandSource": stats.get("demand_source"),
            "mlForecast": stats.get("ml_forecast"),
            "lastSaleDate": str(stats["last_sale_date"]) if stats["last_sale_date"] else None,
            "daysSinceLastSale": stats["days_since_last_sale"],
        },
        "decision": decision,
        "replacementRecommendation": {
            "enabled": True,
            "total": len(replacements),
            "items": replacements,
            "message": (
                "Les remplaçants sont classés selon similarité, ventes, demande, stock et marge."
                if replacements else
                "Aucun remplaçant fiable trouvé dans la même catégorie. Vérifier manuellement les produits proches."
            ),
        },
    }


def list_elimination_recommendations_service(
    db: Session,
    observation_days: int = ELIMINATION_DAYS,
    min_weekly_demand: float = DEFAULT_MIN_WEEKLY_DEMAND,
    replacement_limit: int = DEFAULT_REPLACEMENT_LIMIT,
    only_candidates: bool = False,
    limit: int = 100,
) -> dict:
    if observation_days < 30:
        raise HTTPException(status_code=400, detail="observation_days doit être >= 30")

    anchor_date = _analysis_anchor_date(db)
    products = db.query(Product).order_by(Product.id.desc()).limit(max(1, min(limit, 500))).all()

    items = []
    for product in products:
        stats = _sales_stats_for_sku(db, product.sku, anchor_date, observation_days)
        if ELIMINATION_USE_ML_IN_LIST:
            stats = _merge_ml_demand_into_stats(stats, _fetch_ml_demand_forecast(product.id))
        else:
            stats = _merge_ml_demand_into_stats(stats, None)
        promotion_tested = bool(stats.get("has_discount_signal")) or _has_active_promotion(db, product.id, anchor_date)
        decision = _compute_elimination_decision(
            product=product,
            stats=stats,
            anchor_date=anchor_date,
            observation_days=observation_days,
            min_weekly_demand=min_weekly_demand,
            promotion_tested=promotion_tested,
        )

        if only_candidates and decision["recommendedAction"] not in {
            "LIQUIDATION_OR_PROMO",
            "ELIMINATION_PROGRESSIVE",
            "ELIMINATION_DEFINITIVE",
        }:
            continue

        replacements = []
        if decision["recommendedAction"] in {
            "LIQUIDATION_OR_PROMO",
            "ELIMINATION_PROGRESSIVE",
            "ELIMINATION_DEFINITIVE",
        }:
            replacements = _find_replacements(
                product=product,
                db=db,
                anchor_date=anchor_date,
                period_days=min(90, observation_days),
                limit=replacement_limit,
            )

        items.append({
            "product": _serialize_product(product),
            "salesAnalysis": {
                "periodDays": stats["period_days"],
                "totalSales": _round(stats["total_sales"]),
                "weeklyDemand": _round(stats["weekly_demand"]),
                "historicalWeeklyDemand": _round(stats.get("historical_weekly_demand")),
                "mlWeeklyDemand": _round(stats.get("ml_weekly_demand")),
                "effectiveWeeklyDemand": _round(stats.get("effective_weekly_demand")),
                "demandSource": stats.get("demand_source"),
                "lastSaleDate": str(stats["last_sale_date"]) if stats["last_sale_date"] else None,
                "daysSinceLastSale": stats["days_since_last_sale"],
            },
            "decision": decision,
            "topReplacements": replacements,
        })

    items.sort(key=lambda item: item["decision"]["scoreElimination"], reverse=True)

    return {
        "status": "success",
        "type": "PRODUCT_ELIMINATION_RECOMMENDATIONS_LIST",
        "generatedAt": datetime.utcnow().isoformat(),
        "analysisAnchorDate": str(anchor_date),
        "total": len(items),
        "rules": {
            "watchDays": WATCH_DAYS,
            "dormantDays": DORMANT_DAYS,
            "liquidationDays": LIQUIDATION_DAYS,
            "eliminationDays": ELIMINATION_DAYS,
            "deadStockDays": DEAD_STOCK_DAYS,
            "minWeeklyDemand": min_weekly_demand,
        },
        "items": items,
    }
