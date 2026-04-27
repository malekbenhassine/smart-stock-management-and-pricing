from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.competitor_product_service import (
    bulk_save_scraped_with_matching,
    bulk_save_scraped_competitor_products_service,
    get_competitor_products_by_product_service,
    get_pending_validation_service,
    validate_match_service,
    rematch_product_service,
)


router = APIRouter(prefix="/competitor-products", tags=["competitor-products"])


@router.post("/from-scraping")
def save_scraping_results_with_matching(
    payload=Body(...),
    db: Session = Depends(get_db),
):
    """
    Reçoit les produits scrapés depuis scraping_service.

    Format accepté :
    {
      "items": [...]
    }

    ou directement :
    [...]
    """
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items") or payload.get("products") or []
    else:
        raise HTTPException(status_code=422, detail="Body invalide")

    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="items doit être une liste")

    return bulk_save_scraped_with_matching(items, db)


@router.post("/bulk")
def bulk_save_competitor_products(
    payload=Body(...),
    db: Session = Depends(get_db),
): 
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items") or payload.get("products") or []
    else:
        raise HTTPException(status_code=422, detail="Body invalide")

    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="items doit être une liste")

    return bulk_save_scraped_competitor_products_service(items, db)


@router.get("/pending-validation")
def get_pending_validation(db: Session = Depends(get_db)):
    return get_pending_validation_service(db)


@router.post("/{competitor_product_id}/validate")
def validate_match(
    competitor_product_id: int,
    accepted: bool = Body(..., embed=True),
    produit_id: Optional[int] = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    return validate_match_service(
        competitor_product_id=competitor_product_id,
        accepted=accepted,
        produit_id=produit_id,
        db=db,
    )


@router.post("/rematch-product/{product_id}")
def rematch_product(product_id: int, db: Session = Depends(get_db)):
    return rematch_product_service(product_id, db)


@router.get("/by-product/{product_id}")
def get_competitor_products_by_product(
    product_id: int,
    status: str | None = Query(None, description="MATCHED, MANUAL_REVIEW ou ALL"),
    debug: bool = Query(False, description="Afficher les détails techniques du matching"),
    db: Session = Depends(get_db),
):
    """
    Retourne les produits concurrents liés à un produit interne.

    Par défaut : réponse simple.
    Avec debug=true : détails techniques du matching.
    """
    result = get_competitor_products_by_product_service(product_id, db)

    if status and status.upper() != "ALL":
        wanted_status = status.upper()
        result["items"] = [
            item for item in result["items"]
            if item.get("statutMatching") == wanted_status
        ]

        matched_items = [
            item for item in result["items"]
            if item.get("statutMatching") == "MATCHED"
        ]

        manual_items = [
            item for item in result["items"]
            if item.get("statutMatching") == "MANUAL_REVIEW"
        ]

        prices = [
            item["prixConcurrent"]
            for item in matched_items
            if item.get("prixConcurrent") is not None
        ]

        result["summary"] = {
            "total": len(result["items"]),
            "matched": len(matched_items),
            "manualReview": len(manual_items),
            "bestPrice": min(prices) if prices else None,
            "maxPrice": max(prices) if prices else None,
            "avgPrice": round(sum(prices) / len(prices), 2) if prices else None,
        }

    if not debug:
        for item in result["items"]:
            item.pop("detailsMatching", None)
            item.pop("descriptionConcurrent", None)

    return result