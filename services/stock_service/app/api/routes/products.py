"""
Routes produits.

Workflow métier :
1. L'utilisateur ajoute un produit.
2. Le produit est enregistré.
3. Le scraping concurrentiel démarre automatiquement en arrière-plan.
4. Le scraping_service envoie les produits scrapés vers stock_service.
5. stock_service fait le matching et sauvegarde les produits concurrents matchés.
6. L'utilisateur peut ensuite demander une recommandation de prix.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.models.tables import Product, ProductCompetitor
from app.schemas.schemas import ProductIn, ProductCreate, ProductUpdate, ProductPriceUpdate
from app.services.kpi_service import get_product_kpis_service
from app.services.product_service import (
    get_all_products,
    get_product_by_id_service,
    get_product_pricing_details_service,
    get_product_stock_details_service,
    create_product_service,
    update_product_service,
    delete_product_service,
    calculate_initial_price_recommendation_service,
    update_product_price_service,
)
from app.services.price_recommendation_service import calculate_price_recommendation
from app.services.scraping_client import ScrapingServiceClient


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["products"])


# ──────────────────────────────────────────────────────────────────────────────
# Background task : analyse concurrentielle après création produit
# ──────────────────────────────────────────────────────────────────────────────

def _background_scrape_after_product_creation(product_id: int):
    db = SessionLocal()

    try:
        product = db.query(Product).filter(Product.id == product_id).first()

        if not product:
            logger.warning(f"Produit {product_id} introuvable pour analyse concurrentielle")
            return

        product.analyse_concurrentielle_statut = "RUNNING"
        db.commit()

        client = ScrapingServiceClient()

        scraping_result = client.search_product_on_competitors({
            "id": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "marque": product.marque,
            "description": product.description,
            "categorie": product.categorie,
        })

        if scraping_result.get("status") == "error":
            raise Exception(scraping_result.get("error", "Erreur recherche ciblée inconnue"))

        logger.info(
            f"Analyse concurrentielle terminée pour produit {product_id}: {scraping_result}"
        )

        product = db.query(Product).filter(Product.id == product_id).first()

        if product:
            product.analyse_concurrentielle_statut = "DONE"
            product.analyse_concurrentielle_date = datetime.utcnow()
            db.commit()

    except Exception as exc:
        logger.error(f"Erreur analyse concurrentielle produit {product_id}: {exc}")

        product = db.query(Product).filter(Product.id == product_id).first()

        if product:
            product.analyse_concurrentielle_statut = "FAILED"
            product.analyse_concurrentielle_date = datetime.utcnow()
            db.commit()

    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# Liste produits
# ──────────────────────────────────────────────────────────────────────────────

@router.get("")
def get_products(q: str | None = None, db: Session = Depends(get_db)):
    return get_all_products(db, q)


# ──────────────────────────────────────────────────────────────────────────────
# Création produit + scraping automatique
# ──────────────────────────────────────────────────────────────────────────────

@router.post("")
def create_product(
    payload: ProductCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Ajoute un produit interne.

    Côté utilisateur :
    - il remplit le formulaire
    - il clique sur Enregistrer
    - le backend lance automatiquement l'analyse concurrentielle

    Le scraping est invisible pour l'utilisateur.
    """
    product = create_product_service(payload, db)

    db_product = db.query(Product).filter(Product.id == product["id"]).first()

    if db_product:
        db_product.analyse_concurrentielle_statut = "RUNNING"
        db_product.analyse_concurrentielle_date = None
        db.commit()

    background_tasks.add_task(
        _background_scrape_after_product_creation,
        product["id"],
    )

    return {
        "status": "success",
        "product": product,
        "workflow": {
            "scrapingStarted": True,
            "analysisStatus": "RUNNING",
            "message": "Produit ajouté. Analyse concurrentielle en cours."
        }
    }


# ──────────────────────────────────────────────────────────────────────────────
# Bulk import
# Important : garder cette route avant /{product_id}
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/bulk")
def bulk_import_products(items: list[ProductIn], db: Session = Depends(get_db)):
    count = 0

    for item in items:
        obj = db.query(Product).filter(Product.id == item.id).first()

        if not obj:
            obj = Product(id=item.id)
            db.add(obj)

        obj.sku = item.sku
        obj.nom = item.nom
        obj.categorie = item.categorie
        obj.marque = item.marque
        obj.description = item.description
        obj.prix_cout = item.prixcout
        obj.prix_vente = item.prixvente
        obj.marge_reservee = item.margereservee
        obj.stock_disponible = item.stockdisponible
        obj.stock_reserve = item.stockreserve
        obj.stock_minimum = item.stockminimum
        obj.seuil_max = item.seuilmax
        obj.seuil_min = item.seuilmin
        obj.statut = item.statut
        obj.date_debut_observation = item.datedebutobservation
        obj.date_fin_observation = item.datefinobservation

        count += 1

    db.commit()

    return {
        "status": "success",
        "rows": count,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Détail produit
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    return get_product_by_id_service(product_id, db)


@router.put("/{product_id}")
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    return update_product_service(product_id, payload, db)


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    return delete_product_service(product_id, db)


# ──────────────────────────────────────────────────────────────────────────────
# Statut analyse concurrentielle
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{product_id}/competitive-analysis-status")
def get_competitive_analysis_status(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    matched_count = (
        db.query(ProductCompetitor)
        .filter(
            ProductCompetitor.produit_id == product_id,
            ProductCompetitor.statut_matching == "MATCHED",
        )
        .count()
    )

    manual_review_count = (
        db.query(ProductCompetitor)
        .filter(
            ProductCompetitor.produit_id == product_id,
            ProductCompetitor.statut_matching == "MANUAL_REVIEW",
        )
        .count()
    )

    return {
        "productId": product.id,
        "status": product.analyse_concurrentielle_statut,
        "date": product.analyse_concurrentielle_date,
        "matchedCompetitorProducts": matched_count,
        "manualReviewProducts": manual_review_count,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Détails métier produit
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{product_id}/pricing-details")
def get_product_pricing_details(product_id: int, db: Session = Depends(get_db)):
    return get_product_pricing_details_service(product_id, db)


@router.get("/{product_id}/stock-details")
def get_product_stock_details(product_id: int, db: Session = Depends(get_db)):
    return get_product_stock_details_service(product_id, db)


@router.get("/{product_id}/kpis")
def get_product_kpis(product_id: int, days: int = 30, db: Session = Depends(get_db)):
    try:
        return get_product_kpis_service(product_id, db, days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur calcul KPI: {str(exc)}")


# ──────────────────────────────────────────────────────────────────────────────
# Prix
# ──────────────────────────────────────────────────────────────────────────────

@router.put("/{product_id}/price")
def update_product_price(
    product_id: int,
    payload: ProductPriceUpdate,
    db: Session = Depends(get_db),
):
    return update_product_price_service(
        product_id=product_id,
        new_price=payload.newPrixVente,
        justification=payload.justification,
        db=db,
    )


@router.post("/{product_id}/initial-price-recommendation")
def get_initial_price_recommendation(product_id: int, db: Session = Depends(get_db)):
    """
    Ancienne route.
    Tu peux la garder pour compatibilité avec ton frontend actuel.
    """
    return calculate_initial_price_recommendation_service(product_id, db)


@router.get("/{product_id}/price-recommendation")
def get_price_recommendation(
    product_id: int,
    strategy: str = "competitive",
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    if product.analyse_concurrentielle_statut == "RUNNING":
        return {
            "status": "pending",
            "productId": product.id,
            "message": "Analyse concurrentielle en cours. Réessayez dans quelques instants."
        }

    return calculate_price_recommendation(
        product=product,
        db=db,
        strategy=strategy,
    )


@router.post("/{product_id}/price-recommendation")
def post_price_recommendation(
    product_id: int,
    strategy: str = Body("competitive", embed=True),
    min_margin: float | None = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    if product.analyse_concurrentielle_statut == "RUNNING":
        return {
            "status": "pending",
            "productId": product.id,
            "message": "Analyse concurrentielle en cours. Réessayez dans quelques instants."
        }

    return calculate_price_recommendation(
        product=product,
        db=db,
        min_margin=min_margin,
        strategy=strategy,
    )