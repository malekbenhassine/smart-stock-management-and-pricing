from __future__ import annotations

from statistics import mean
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.tables import Product, ProductCompetitor


ACCEPTED_COMPETITOR_STATUSES = {
    "MATCHED",
    "AUTO_MATCHED",
    "VALIDATED",
    "MANUAL_VALIDATED",
}

EXCLUDED_COMPETITOR_STATUSES = {
    "MANUAL_REVIEW",
    "IGNORED",
    "DEMATCHED",
    "REJECTED",
}


# -----------------------------------------------------------------------------
# Helpers robustes : compatibilité ancien/nouveau code
# -----------------------------------------------------------------------------

def _get_attr(obj: Any, *names: str, default=None):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _normalize_status(value) -> str:
    """
    Normalise les statuts venant de différentes versions du projet.

    Exemples :
    - matched -> MATCHED
    - manual validated -> MANUAL_VALIDATED
    - manual-validated -> MANUAL_VALIDATED
    """
    if value is None:
        return ""

    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def _normalize_margin(value) -> float:
    margin = _safe_float(value, 0.2)

    if margin is None:
        return 0.2

    # Si l'utilisateur stocke 20 au lieu de 0.20
    if margin > 1:
        return margin / 100

    if margin < 0:
        return 0.2

    return margin


def _calculate_price_floor(prix_cout: float | None, marge_reservee) -> float | None:
    if prix_cout is None or prix_cout <= 0:
        return None

    margin = _normalize_margin(marge_reservee)
    return _round_price(prix_cout * (1 + margin))


def _calculate_direction(prix_actuel: float | None, prix_recommande: float | None):
    if prix_actuel is None or prix_recommande is None:
        return "KEEP", None, None

    ecart = round(prix_recommande - prix_actuel, 2)

    if prix_actuel == 0:
        ecart_pct = None
    else:
        ecart_pct = round((ecart / prix_actuel) * 100, 2)

    if abs(ecart) < 0.01:
        direction = "KEEP"
    elif ecart > 0:
        direction = "UP"
    else:
        direction = "DOWN"

    return direction, ecart, ecart_pct


def _competitor_status(pc) -> str:
    """
    IMPORTANT : on privilégie statutMatching/statut_matching.

    Dans ta base, il existe parfois une ancienne colonne match_status = ignored
    alors que la vraie colonne utilisée par le projet est statutMatching = MATCHED.
    La recommandation doit donc lire statutMatching en priorité.
    """
    value = _get_attr(
        pc,
        "statut_matching",      # SQLAlchemy -> colonne DB "statutMatching"
        "statutMatching",
        "status",
        "match_status",        # ancien champ : seulement fallback
        "matchStatus",
        default=None,
    )

    return _normalize_status(value)


def _competitor_score(pc) -> float:
    value = _get_attr(
        pc,
        "score_matching",       # SQLAlchemy -> colonne DB "scoreMatching"
        "scoreMatching",
        "match_score",         # ancien champ : seulement fallback
        "matchScore",
        default=0,
    )

    return _safe_float(value, 0) or 0


def _competitor_price(pc) -> float | None:
    price = _get_attr(
        pc,
        "prix_concurrent",      # SQLAlchemy -> colonne DB "prixConcurrent"
        "prixConcurrent",
        "price",
        default=None,
    )

    price = _safe_float(price, None)

    if price is None or price <= 0:
        return None

    return price


def _is_usable_competitor(pc) -> bool:
    """
    Règle finale demandée :
    La recommandation concurrence utilise uniquement les statuts :
    MATCHED, AUTO_MATCHED, VALIDATED, MANUAL_VALIDATED.

    Les statuts MANUAL_REVIEW, IGNORED, DEMATCHED, REJECTED sont exclus.
    Le score ne doit pas bloquer une ligne validée manuellement.
    """
    price = _competitor_price(pc)
    if price is None:
        return False

    status = _competitor_status(pc)

    if status in EXCLUDED_COMPETITOR_STATUSES:
        return False

    if status in ACCEPTED_COMPETITOR_STATUSES:
        return True

    return False


def _serialize_competitor(pc) -> dict:
    return {
        "id": _get_attr(pc, "id"),
        "concurrentId": _get_attr(pc, "concurrent_id", "concurrentId"),
        "produit_id": _get_attr(pc, "produit_id", "productId"),
        "nomProduit": _get_attr(pc, "nom_produit", "nomProduit"),
        "urlProduit": _get_attr(pc, "url_produit", "urlProduit"),
        "skuConcurrent": _get_attr(pc, "sku_concurrent", "skuConcurrent"),
        "prixConcurrent": _round_price(_competitor_price(pc)),
        "scoreMatching": _competitor_score(pc),
        "statutMatching": _competitor_status(pc),
        "fiable": _get_attr(pc, "fiable", default=None),
    }


def _internal_price_recommendation(
    product: Product,
    prix_actuel: float | None,
    prix_cout: float | None,
    marge_minimale: float,
    prix_plancher: float | None,
    reason: str,
    competitor_products: list[ProductCompetitor] | None = None,
):
    competitor_products = competitor_products or []

    if prix_plancher is not None and prix_plancher > 0:
        prix_recommande = prix_plancher
    elif prix_cout is not None and prix_cout > 0:
        prix_recommande = prix_cout * (1 + marge_minimale)
    elif prix_actuel is not None and prix_actuel > 0:
        prix_recommande = prix_actuel
    else:
        prix_recommande = 0

    prix_recommande = _round_price(prix_recommande)
    direction, ecart, ecart_pct = _calculate_direction(prix_actuel, prix_recommande)

    return {
        "status": "success",
        "source": "INTERNE_COUT_MARGE",
        "productId": product.id,
        "sku": product.sku,
        "nom": product.nom,
        "prixActuel": prix_actuel,
        "prixCout": prix_cout,
        "margeMinimale": marge_minimale,
        "prixPlancher": prix_plancher,
        "prixRecommande": prix_recommande,
        "recommended_price": prix_recommande,
        "direction": direction,
        "ecartPrixActuel": ecart,
        "ecartPourcentage": ecart_pct,
        "variationPercent": ecart_pct,
        "competitorCount": len(competitor_products),
        "usableCompetitorCount": 0,
        "prixConcurrentMin": None,
        "prixConcurrentMoyen": None,
        "prixConcurrentMax": None,
        "market": None,
        "competitorsUsed": [],
        "competitorsFound": [_serialize_competitor(pc) for pc in competitor_products],
        "message": reason,
    }


# -----------------------------------------------------------------------------
# Service principal
# -----------------------------------------------------------------------------

def calculate_price_recommendation(product_id: int, db: Session) -> dict:
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable.")

    prix_actuel = _safe_float(_get_attr(product, "prix_vente", "prixVente"), None)
    prix_cout = _safe_float(_get_attr(product, "prix_cout", "prixCout"), None)

    marge_minimale = _normalize_margin(
        _get_attr(product, "marge_reservee", "margeReservee", default=0.2)
    )

    prix_plancher = _calculate_price_floor(prix_cout, marge_minimale)

    competitor_products = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.produit_id == product_id)
        .all()
    )

    usable_competitors = [
        pc for pc in competitor_products if _is_usable_competitor(pc)
    ]

    competitor_prices = [
        _competitor_price(pc)
        for pc in usable_competitors
    ]
    competitor_prices = [p for p in competitor_prices if p is not None and p > 0]

    if not competitor_prices:
        return _internal_price_recommendation(
            product=product,
            prix_actuel=prix_actuel,
            prix_cout=prix_cout,
            marge_minimale=marge_minimale,
            prix_plancher=prix_plancher,
            competitor_products=competitor_products,
            reason=(
                "Aucun concurrent validé exploitable pour la recommandation. "
                "Seuls les statuts MATCHED, AUTO_MATCHED, VALIDATED et MANUAL_VALIDATED sont utilisés. "
                "La recommandation est donc basée sur les données internes."
            ),
        )

    prix_min = min(competitor_prices)
    prix_max = max(competitor_prices)
    prix_moyen = mean(competitor_prices)

    # Stratégie simple, stable et défendable :
    # - prix marché = moyenne des concurrents validés
    # - positionnement = 2 % sous la moyenne
    # - ne jamais descendre sous le prix plancher coût + marge
    target_market_price = prix_moyen * 0.98

    if prix_plancher is not None:
        prix_recommande = max(prix_plancher, target_market_price)
    else:
        prix_recommande = target_market_price

    prix_recommande = _round_price(prix_recommande)
    direction, ecart, ecart_pct = _calculate_direction(prix_actuel, prix_recommande)

    return {
        "status": "success",
        "source": "HYBRIDE_INTERNE_CONCURRENCE",
        "productId": product.id,
        "sku": product.sku,
        "nom": product.nom,
        "prixActuel": prix_actuel,
        "prixCout": prix_cout,
        "margeMinimale": marge_minimale,
        "prixPlancher": prix_plancher,
        "prixRecommande": prix_recommande,
        "recommended_price": prix_recommande,
        "direction": direction,
        "ecartPrixActuel": ecart,
        "ecartPourcentage": ecart_pct,
        "variationPercent": ecart_pct,
        "competitorCount": len(competitor_products),
        "usableCompetitorCount": len(usable_competitors),
        "prixConcurrentMin": _round_price(prix_min),
        "prixConcurrentMoyen": _round_price(prix_moyen),
        "prixConcurrentMax": _round_price(prix_max),
        "market": {
            "min": _round_price(prix_min),
            "avg": _round_price(prix_moyen),
            "average": _round_price(prix_moyen),
            "max": _round_price(prix_max),
        },
        "competitorsUsed": [_serialize_competitor(pc) for pc in usable_competitors],
        "competitorsFound": [_serialize_competitor(pc) for pc in competitor_products],
        "message": (
            "Recommandation calculée avec les produits concurrents validés. "
            "Statuts acceptés : MATCHED, AUTO_MATCHED, VALIDATED, MANUAL_VALIDATED."
        ),
    }


def get_price_recommendation_service(product_id: int, db: Session) -> dict:
    return calculate_price_recommendation(product_id, db)
