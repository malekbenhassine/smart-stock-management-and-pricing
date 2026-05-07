from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tables import Product, ProductCompetitor
from app.services.scraping_client import ScrapingServiceClient
from app.services.competitor_product_service import (
    bulk_save_scraped_with_matching,
    bulk_save_scraped_competitor_products_service,
    get_competitor_products_by_product_service,
    get_pending_validation_service,
    validate_match_service,
    rematch_product_service,
    unmatch_competitor_product_service,
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
    """
    Sauvegarde simple des produits concurrents scrapés.
    """
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
    """
    Retourne les matchs en attente de validation.
    """
    return get_pending_validation_service(db)


@router.post("/{competitor_product_id}/validate")
def validate_match(
    competitor_product_id: int,
    accepted: bool = Body(True, embed=True),
    produit_id: Optional[int] = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    """
    Valide ou refuse un produit concurrent.
    """
    return validate_match_service(
        competitor_product_id=competitor_product_id,
        accepted=accepted,
        produit_id=produit_id,
        db=db,
    )


@router.post("/{competitor_product_id}/unmatch")
def unmatch_competitor_product(
    competitor_product_id: int,
    db: Session = Depends(get_db),
):
    """
    Dématche manuellement un produit concurrent (MATCHED → IGNORED).
    Ce choix est respecté lors des futurs scrapings automatiques,
    sauf si le score est 100 (correspondance exacte certaine).
    """
    return unmatch_competitor_product_service(competitor_product_id, db)




@router.post("/{competitor_product_id}/ignore")
def ignore_competitor_product(
    competitor_product_id: int,
    db: Session = Depends(get_db),
):
    """Ignore un produit concurrent : il ne sera pas utilisé dans la recommandation."""
    pc = db.query(ProductCompetitor).filter(ProductCompetitor.id == competitor_product_id).first()

    if not pc:
        raise HTTPException(status_code=404, detail="Produit concurrent introuvable")

    pc.statut_matching = "IGNORED"
    pc.fiable = False

    details = pc.details_matching or {}
    details["status"] = "IGNORED"
    details["ignored_manually"] = True
    pc.details_matching = details

    db.commit()
    db.refresh(pc)

    return {
        "status": "success",
        "message": "Produit concurrent ignoré",
        "item": {
            "id": pc.id,
            "produit_id": pc.produit_id,
            "concurrentId": pc.concurrent_id,
            "urlProduit": pc.url_produit,
            "skuConcurrent": pc.sku_concurrent,
            "nomProduit": pc.nom_produit,
            "prixConcurrent": pc.prix_concurrent,
            "scoreMatching": pc.score_matching,
            "statutMatching": pc.statut_matching,
            "fiable": pc.fiable,
        },
    }


@router.post("/{competitor_product_id}/manual-review")
def put_competitor_product_in_manual_review(
    competitor_product_id: int,
    db: Session = Depends(get_db),
):
    """Remet un produit concurrent en revue manuelle."""
    pc = db.query(ProductCompetitor).filter(ProductCompetitor.id == competitor_product_id).first()

    if not pc:
        raise HTTPException(status_code=404, detail="Produit concurrent introuvable")

    pc.statut_matching = "MANUAL_REVIEW"
    pc.fiable = False

    details = pc.details_matching or {}
    details["status"] = "MANUAL_REVIEW"
    details["manual_review_requested"] = True
    pc.details_matching = details

    db.commit()
    db.refresh(pc)

    return {
        "status": "success",
        "message": "Produit remis en revue manuelle",
        "item": {
            "id": pc.id,
            "produit_id": pc.produit_id,
            "concurrentId": pc.concurrent_id,
            "urlProduit": pc.url_produit,
            "skuConcurrent": pc.sku_concurrent,
            "nomProduit": pc.nom_produit,
            "prixConcurrent": pc.prix_concurrent,
            "scoreMatching": pc.score_matching,
            "statutMatching": pc.statut_matching,
            "fiable": pc.fiable,
        },
    }


@router.post("/auto-fix-100")
def auto_fix_100_matches(
    product_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Corrige les anciens produits avec score 100 mais statut non exploitable."""
    query = db.query(ProductCompetitor).filter(ProductCompetitor.score_matching >= 100)

    if product_id is not None:
        query = query.filter(ProductCompetitor.produit_id == product_id)

    rows = query.all()
    fixed = 0

    for pc in rows:
        current_status = str(pc.statut_matching or "").upper()
        if current_status in {"", "MANUAL_REVIEW", "IGNORED", "REJECTED", "DEMATCHED"}:
            pc.statut_matching = "MATCHED"
            pc.fiable = True
            details = pc.details_matching or {}
            details["status"] = "MATCHED"
            details["auto_fixed_100"] = True
            pc.details_matching = details
            fixed += 1

    db.commit()

    return {
        "status": "success",
        "fixed": fixed,
        "message": f"{fixed} produit(s) concurrent(s) corrigé(s).",
    }


@router.post("/rematch-product/{product_id}")
def rematch_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    """
    Recalcule le matching pour un produit interne.
    """
    return rematch_product_service(product_id, db)


# ── Job store en mémoire pour le scraping asynchrone ─────────────────────
import threading as _threading
import time as _time

_scrape_jobs: dict[int, dict] = {}
_scrape_lock = _threading.Lock()


def _run_scrape_job(product_id: int, product_data: dict, debug: bool) -> None:
    """Exécuté dans un thread daemon — ne bloque pas le serveur HTTP."""
    from app.core.database import SessionLocal
    client = ScrapingServiceClient()

    scraping_result = client.search_product_on_competitors(product_data, debug=debug)

    db = SessionLocal()
    try:
        db.expire_all()
        products_result = get_competitor_products_by_product_service(product_id, db)
    except Exception as e:
        products_result = {"error": str(e)}
    finally:
        db.close()

    with _scrape_lock:
        _scrape_jobs[product_id] = {
            "status": scraping_result.get("status", "success"),
            "scraping": scraping_result,
            "products": products_result,
            "finished_at": _time.time(),
        }


@router.post("/scrape-product/{product_id}")
def scrape_product_and_return_results(
    product_id: int,
    debug: bool = Query(False, description="Afficher les détails techniques du scraping"),
    db: Session = Depends(get_db),
):
    """
    FIX timeout : Lance le scraping en arrière-plan (thread daemon).
    Répond immédiatement avec status=started.
    Interroger GET /scrape-product/{id}/status pour les résultats.
    Si un résultat récent (<5 min) existe déjà, il est retourné directement.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit interne introuvable")

    with _scrape_lock:
        existing = _scrape_jobs.get(product_id)

    # Résultat frais disponible → retour direct
    if existing and existing.get("status") not in ("running",):
        age = _time.time() - existing.get("finished_at", 0)
        if age < 300:
            result = existing.get("products", {})
            result["scraping"] = existing.get("scraping", {})
            result["cached"] = True
            return result

    # Job déjà en cours → signaler
    if existing and existing.get("status") == "running":
        return {
            "status": "running",
            "message": "Scraping déjà en cours. Vérifiez /scrape-product/{product_id}/status",
            "product_id": product_id,
            "poll_url": f"/competitor-products/scrape-product/{product_id}/status",
        }

    with _scrape_lock:
        _scrape_jobs[product_id] = {"status": "running", "started_at": _time.time()}

    product_data = {
        "id": product.id,
        "sku": product.sku,
        "nom": product.nom,
        "marque": product.marque,
        "description": product.description,
        "categorie": product.categorie,
    }

    t = _threading.Thread(
        target=_run_scrape_job,
        args=(product_id, product_data, debug),
        daemon=True,
    )
    t.start()

    return {
        "status": "started",
        "message": "Scraping lancé en arrière-plan. Interrogez le endpoint /status.",
        "product_id": product_id,
        "poll_url": f"/competitor-products/scrape-product/{product_id}/status",
    }


@router.get("/scrape-product/{product_id}/status")
def get_scrape_status(
    product_id: int,
    db: Session = Depends(get_db),
):
    """
    Retourne l'état du scraping asynchrone.
      status=running   → en cours, réessayer dans quelques secondes
      status=success   → terminé OK, résultats dans 'products'
      status=timeout   → scraping_service trop lent
      status=not_started → aucun job en mémoire, retourne les données DB existantes
    """
    with _scrape_lock:
        job = dict(_scrape_jobs.get(product_id, {}))

    if not job:
        result = get_competitor_products_by_product_service(product_id, db)
        result["status"] = "not_started"
        return result

    if job.get("status") == "running":
        elapsed = round(_time.time() - job.get("started_at", _time.time()), 1)
        return {
            "status": "running",
            "product_id": product_id,
            "elapsed_seconds": elapsed,
            "message": "Scraping en cours…",
        }

    result = job.get("products", {})
    result["scraping"] = job.get("scraping", {})
    result["status"] = job.get("status", "success")
    return result


@router.get("/by-product/{product_id}")
def get_competitor_products_by_product(
    product_id: int,
    status: str | None = Query(None, description="MATCHED, MANUAL_REVIEW, REJECTED ou ALL"),
    debug: bool = Query(False, description="Afficher les détails techniques du matching"),
    db: Session = Depends(get_db),
):
    """
    Retourne les produits concurrents liés à un produit interne.

    Par défaut : réponse simple.
    Avec debug=true : détails techniques du matching.
    """
    result = get_competitor_products_by_product_service(product_id, db)

    items = result.get("items", [])

    if status and status.upper() != "ALL":
        wanted_status = status.upper()

        items = [
            item for item in items
            if str(item.get("statutMatching") or item.get("statut_matching") or "").upper()
            == wanted_status
        ]

        result["items"] = items

        matched_items = [
            item for item in items
            if str(item.get("statutMatching") or item.get("statut_matching") or "").upper()
            == "MATCHED"
        ]

        manual_items = [
            item for item in items
            if str(item.get("statutMatching") or item.get("statut_matching") or "").upper()
            == "MANUAL_REVIEW"
        ]

        prices = [
            item.get("prixConcurrent") or item.get("prix_concurrent")
            for item in matched_items
            if item.get("prixConcurrent") is not None or item.get("prix_concurrent") is not None
        ]

        result["summary"] = {
            "total": len(items),
            "matched": len(matched_items),
            "manualReview": len(manual_items),
            "bestPrice": min(prices) if prices else None,
            "maxPrice": max(prices) if prices else None,
            "avgPrice": round(sum(prices) / len(prices), 2) if prices else None,
        }

    if not debug:
        for item in result.get("items", []):
            item.pop("detailsMatching", None)
            item.pop("descriptionConcurrent", None)
            item.pop("description_concurrent", None)

    return result