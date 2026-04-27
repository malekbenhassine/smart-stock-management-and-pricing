from __future__ import annotations

from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tables import Product, ProductCompetitor


DEFAULT_MIN_MARGIN = 0.20


def _normalize_margin(value: Optional[float]) -> float:
    if value is None:
        return DEFAULT_MIN_MARGIN

    if value > 1:
        return value / 100

    return value


def _is_available(value: Optional[str]) -> bool:
    if not value:
        return True

    text = value.lower()

    bad_words = [
        "hors stock",
        "rupture",
        "indisponible",
        "out of stock",
        "non disponible",
    ]

    return not any(word in text for word in bad_words)


def _effective_price(pc: ProductCompetitor) -> float:
    if pc.is_promo and pc.ancien_prix_concurrent and pc.ancien_prix_concurrent > 0:
        return pc.ancien_prix_concurrent

    return pc.prix_concurrent


def calculate_price_recommendation(
    product: Product,
    db: Session,
    min_margin: Optional[float] = None,
    strategy: str = "competitive",
) -> dict:
    effective_margin = _normalize_margin(
        min_margin if min_margin is not None else product.marge_reservee
    )

    price_floor = None

    if product.prix_cout and product.prix_cout > 0:
        price_floor = round(product.prix_cout * (1 + effective_margin), 2)

    competitor_products = (
        db.query(ProductCompetitor)
        .filter(
            ProductCompetitor.produit_id == product.id,
            ProductCompetitor.statut_matching == "MATCHED",
            ProductCompetitor.score_matching >= 75,
            ProductCompetitor.prix_concurrent.isnot(None),
        )
        .all()
    )

    usable = []

    for pc in competitor_products:
        if not pc.prix_concurrent or pc.prix_concurrent <= 0:
            continue

        available = _is_available(pc.disponibilite)
        reference_price = _effective_price(pc)

        if not reference_price or reference_price <= 0:
            continue

        weight = (pc.score_matching or 75) / 100

        if not available:
            weight *= 0.45

        if pc.is_promo:
            weight *= 0.70

        if not pc.fiable:
            weight *= 0.50

        usable.append({
            "competitorProductId": pc.id,
            "concurrentId": pc.concurrent_id,
            "nomProduit": pc.nom_produit,
            "urlProduit": pc.url_produit,

            "prixActuelConcurrent": pc.prix_concurrent,
            "ancienPrixConcurrent": pc.ancien_prix_concurrent,
            "prixReferenceUtilise": reference_price,

            "isPromo": pc.is_promo,
            "disponibilite": pc.disponibilite,
            "available": available,

            "scoreMatching": pc.score_matching,
            "weight": round(weight, 3),
        })

    if not usable:
        fallback = product.prix_vente

        if fallback is None and price_floor is not None:
            fallback = price_floor

        return {
            "productId": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "prixActuel": product.prix_vente,
            "prixCout": product.prix_cout,
            "margeMinimale": effective_margin,
            "prixPlancher": price_floor,
            "prixRecommande": fallback,
            "direction": "STABLE",
            "variationPercent": 0,
            "source": "NO_COMPETITOR_MATCH",
            "competitorCount": len(competitor_products),
            "usableCompetitorCount": 0,
            "message": "Aucun prix concurrent matché fiable. Recommandation basée sur le prix actuel ou le prix plancher.",
        }

    prices = [x["prixReferenceUtilise"] for x in usable]
    weights = [x["weight"] for x in usable]

    median_price = median(prices)

    total_weight = sum(weights)
    weighted_price = (
        sum(item["prixReferenceUtilise"] * item["weight"] for item in usable) / total_weight
        if total_weight > 0
        else median_price
    )

    market_reference = round((median_price + weighted_price) / 2, 2)

    if strategy == "premium":
        recommended = market_reference * 1.03
    elif strategy == "aligned":
        recommended = market_reference
    else:
        recommended = market_reference * 0.99

    if price_floor is not None:
        recommended = max(recommended, price_floor)

    recommended = round(recommended, 2)

    current_price = product.prix_vente or 0

    if current_price > 0:
        variation_percent = round(((recommended - current_price) / current_price) * 100, 2)
    else:
        variation_percent = None

    if current_price == 0:
        direction = "SET_PRICE"
    elif recommended > current_price:
        direction = "UP"
    elif recommended < current_price:
        direction = "DOWN"
    else:
        direction = "STABLE"

    return {
        "productId": product.id,
        "sku": product.sku,
        "nom": product.nom,

        "prixActuel": product.prix_vente,
        "prixCout": product.prix_cout,
        "margeMinimale": effective_margin,
        "prixPlancher": price_floor,

        "prixRecommande": recommended,
        "direction": direction,
        "variationPercent": variation_percent,

        "strategy": strategy,
        "source": "COMPETITOR_MATCHING",

        "market": {
            "min": min(prices),
            "max": max(prices),
            "median": round(median_price, 2),
            "weighted": round(weighted_price, 2),
            "reference": market_reference,
        },

        "competitorCount": len(competitor_products),
        "usableCompetitorCount": len(usable),
        "promoCompetitorCount": len([x for x in usable if x["isPromo"]]),

        "competitorsUsed": usable,

        "message": "Prix recommandé calculé avec les produits concurrents matchés, les promotions, la disponibilité, le score de matching, le coût et la marge minimale.",
    }