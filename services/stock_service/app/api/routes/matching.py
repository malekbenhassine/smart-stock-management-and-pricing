"""
Routes pour le matching produit et la recommandation de prix.

Endpoints :
  POST /matching/scraping-results          → sauvegarde avec matching
  GET  /matching/pending-validation        → liste des matchs manuels
  POST /matching/validate/{id}             → valider/rejeter un match
  POST /matching/rematch-product/{id}      → re-matcher un produit interne
  GET  /products/{id}/price-recommendation → recommandation de prix
  POST /products/{id}/price-recommendation → recommandation avec params custom
"""

from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tables import Product
from app.services.competitor_product_service import (
    bulk_save_scraped_with_matching,
    get_pending_validation_service,
    match_new_internal_product,
    validate_match_service,
)
from app.services.price_recommendation_service import calculate_price_recommendation

router = APIRouter(tags=["matching"])


# ──────────────────────────────────────────────────────────────────────────────
# Ingestion de résultats de scraping avec matching
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/matching/scraping-results", summary="Sauvegarde résultats scraping avec matching")
def save_scraping_results_with_matching(
    payload=Body(...),
    db: Session = Depends(get_db),
):
    """
    Accepte une liste de produits scrapés (ou un dict {'items': [...]})
    et les matche automatiquement avec les produits internes.

    Règles de scoring :
      >= 75  → sauvegardé automatiquement (match_status='auto')
       60-74 → sauvegardé en attente de validation (match_status='manual')
      < 60   → ignoré
    """
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items") or payload.get("products") or []
    else:
        raise HTTPException(status_code=422, detail="Body invalide : liste ou {'items': [...]}")

    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="items doit être une liste")

    return bulk_save_scraped_with_matching(items, db)


# ──────────────────────────────────────────────────────────────────────────────
# Validation manuelle
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/matching/pending-validation", summary="Matchs en attente de validation manuelle")
def get_pending_validation(db: Session = Depends(get_db)):
    return get_pending_validation_service(db)


@router.post("/matching/validate/{competitor_product_id}", summary="Valider ou rejeter un match")
def validate_match(
    competitor_product_id: int,
    accepted: bool = Body(..., embed=True),
    produit_id: Optional[int] = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    """
    - accepted=true  → confirme le match (match_status='auto')
    - accepted=false + produit_id → lie à un autre produit interne
    - accepted=false sans produit_id → ignore définitivement (match_status='ignored')
    """
    return validate_match_service(competitor_product_id, accepted, produit_id, db)


# ──────────────────────────────────────────────────────────────────────────────
# Re-matching d'un produit interne
# ──────────────────────────────────────────────────────────────────────────────
@router.post(
    "/matching/rematch-product/{product_id}",
    summary="Re-matcher un produit interne contre tous les produits concurrents existants",
)
def rematch_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    matched = match_new_internal_product(product, db)
    return {
        "produit_id": product_id,
        "nom": product.nom,
        "matches_found": len(matched),
        "matches": matched,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Recommandation de prix
# ──────────────────────────────────────────────────────────────────────────────
@router.get(
    "/products/{product_id}/price-recommendation",
    summary="Recommandation de prix basée sur les concurrents matchés",
)
def get_price_recommendation(
    product_id: int,
    strategy: str = "competitive",
    db: Session = Depends(get_db),
):
    """
    Stratégies disponibles :
      - competitive : 3% sous la médiane concurrente (défaut)
      - aligned     : égal à la médiane concurrente
      - premium     : 3% au-dessus de la médiane concurrente
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    return calculate_price_recommendation(product, db, strategy=strategy)


@router.post(
    "/products/{product_id}/price-recommendation",
    summary="Recommandation de prix avec paramètres personnalisés",
)
def post_price_recommendation(
    product_id: int,
    strategy: str = Body("competitive", embed=True),
    min_margin: Optional[float] = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    """
    Paramètres :
      - strategy   : 'competitive' | 'aligned' | 'premium'
      - min_margin : marge minimale (ex. 0.15 pour 15%).
                     Si omis, utilise marge_reservee du produit ou 10%.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    return calculate_price_recommendation(product, db, min_margin=min_margin, strategy=strategy)
