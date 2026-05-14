from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.services.stock_movement_service import record_stock_trace_only
from app.core.database import get_db, SessionLocal
from app.models.tables import Product, ProductCompetitor
from app.schemas.schemas import (
    ProductIn,
    ProductCreate,
    ProductUpdate,
    ProductPriceUpdate,
    PriceApprovalRequest,
)
from app.services.kpi_service import get_product_kpis_service
from app.services.product_service import (
    get_all_products,
    get_product_by_id_service,
    get_product_pricing_details_service,
    get_product_stock_details_service,
    create_product_service,
    update_product_service,
    delete_product_service,
    get_pending_pricing_products_service,
    update_product_price_service,
    approve_product_price_service,
)
from app.services.price_recommendation_service import calculate_price_recommendation
from app.services.scraping_client import ScrapingServiceClient
from app.services.elimination_recommendation_service import (
    get_product_elimination_recommendation_service,
    list_elimination_recommendations_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["products"])


def _competitor_validation_summary(product_id: int, db: Session) -> dict:
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
        "matchedCompetitorProducts": matched_count,
        "manualReviewProducts": manual_review_count,
    }


def _block_competitive_recommendation_if_validation_required(
    product: Product,
    strategy: str,
    db: Session,
) -> dict | None:
    """
    La recommandation concurrentielle ne doit pas être affichée tant qu'il existe
    des produits concurrents à accepter/refuser par le responsable pricing.
    """
    if (strategy or "competitive").lower() not in ("competitive", "competition", "concurrence"):
        return None

    summary = _competitor_validation_summary(product.id, db)

    # Correction finale :
    # On ne bloque PLUS la recommandation s'il existe déjà au moins un concurrent validé.
    # Exemple réel : produit 345 => 2 MATCHED + 1 MANUAL_REVIEW.
    # Dans ce cas, la recommandation doit utiliser les 2 MATCHED et ignorer le MANUAL_REVIEW.
    if summary["manualReviewProducts"] > 0 and summary["matchedCompetitorProducts"] <= 0:
        return {
            "status": "validation_required",
            "productId": product.id,
            **summary,
            "message": (
                "Aucun concurrent validé n'est disponible. "
                "Les produits concurrents en revue manuelle doivent être acceptés ou refusés "
                "avant d'afficher une recommandation basée sur la concurrence."
            ),
        }

    return None



def _background_scrape_after_product_creation(product_id: int):
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            logger.warning("Produit %s introuvable pour analyse concurrentielle", product_id)
            return

        product.analyse_concurrentielle_statut = "RUNNING"
        product.analyse_concurrentielle_date = None
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

        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            product.analyse_concurrentielle_statut = "DONE"
            product.analyse_concurrentielle_date = datetime.utcnow()
            # Le prix reste à valider par le responsable pricing.
            if hasattr(product, "statut_prix") and product.statut_prix != "PRIX_VALIDE":
                product.statut_prix = "RECOMMANDATION_PRETE"
            db.commit()

    except Exception as exc:
        logger.error("Erreur analyse concurrentielle produit %s: %s", product_id, exc)
        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            product.analyse_concurrentielle_statut = "FAILED"
            product.analyse_concurrentielle_date = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.get("")
def get_products(q: str | None = None, db: Session = Depends(get_db)):
    return get_all_products(db, q)


@router.post("")
def create_product(
    payload: ProductCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    product = create_product_service(payload, db)

    db_product = db.query(Product).filter(Product.id == product["id"]).first()
    if db_product:
        db_product.analyse_concurrentielle_statut = "RUNNING"
        db_product.analyse_concurrentielle_date = None
        if hasattr(db_product, "statut_prix"):
            db_product.statut_prix = "EN_ATTENTE_PRICING"
        db.commit()

    background_tasks.add_task(_background_scrape_after_product_creation, product["id"])

    return {
        "status": "success",
        "product": product,
        "workflow": {
            "scrapingStarted": True,
            "analysisStatus": "RUNNING",
            "statutPrix": "EN_ATTENTE_PRICING",
            "message": "Produit ajouté. Analyse concurrentielle lancée. Le prix final sera validé par le responsable pricing.",
        },
    }


@router.post("/bulk")
def bulk_import_products(items: list[ProductIn], db: Session = Depends(get_db)):
    rows_processed = 0
    created_count = 0
    updated_count = 0
    movements_created = 0
    ignored_rows = []
    product_ids = []

    for index, item in enumerate(items, start=1):
        if not item.sku or not str(item.sku).strip():
            ignored_rows.append({"row": index, "reason": "SKU manquant."})
            continue

        if not item.nom or not str(item.nom).strip():
            ignored_rows.append(
                {
                    "row": index,
                    "sku": item.sku,
                    "reason": "Nom produit manquant.",
                }
            )
            continue

        sku = str(item.sku).strip()

        obj = db.query(Product).filter(Product.sku == sku).first()

        is_new = obj is None

        if is_new:
            obj = Product()
            db.add(obj)
            old_stock = 0
            created_count += 1
        else:
            old_stock = int(obj.stock_disponible or 0)
            updated_count += 1

        obj.sku = sku
        obj.nom = str(item.nom).strip()
        obj.categorie = item.categorie
        obj.marque = item.marque
        obj.description = item.description
        obj.prix_cout = item.prixcout
        obj.prix_vente = item.prixvente
        obj.marge_reservee = item.margereservee
        obj.stock_disponible = item.stockdisponible or 0
        obj.stock_reserve = item.stockreserve or 0
        obj.stock_minimum = item.stockminimum
        obj.seuil_max = item.seuilmax
        obj.seuil_min = item.seuilmin
        obj.statut = item.statut or "actif"
        obj.date_debut_observation = item.datedebutobservation
        obj.date_fin_observation = item.datefinobservation

        if hasattr(obj, "statut_prix") and obj.statut_prix != "PRIX_VALIDE":
            obj.statut_prix = "EN_ATTENTE_PRICING"

        if hasattr(obj, "analyse_concurrentielle_statut"):
            obj.analyse_concurrentielle_statut = "NOT_STARTED"
            obj.analyse_concurrentielle_date = None

        db.flush()

        product_ids.append(obj.id)

        new_stock = int(obj.stock_disponible or 0)
        diff = new_stock - old_stock

        if is_new and new_stock > 0:
            movement = record_stock_trace_only(
                db=db,
                produit_id=obj.id,
                movement_type="ENTREE",
                quantite=new_stock,
                justification="Stock initial importé depuis fichier",
            )

            if movement:
                movements_created += 1

        elif not is_new and diff != 0:
            if diff > 0:
                movement_type = "AJUSTEMENT_POSITIF"
                qty = diff
            else:
                movement_type = "AJUSTEMENT_NEGATIF"
                qty = abs(diff)

            movement = record_stock_trace_only(
                db=db,
                produit_id=obj.id,
                movement_type=movement_type,
                quantite=qty,
                justification="Ajustement automatique après import produit",
            )

            if movement:
                movements_created += 1

        rows_processed += 1

    db.commit()

    return {
        "status": "success",
        "message": "Import produits terminé. L'id CSV a été ignoré, l'upsert s'est fait par SKU.",
        "rows_received": len(items),
        "rows_processed": rows_processed,
        "rows": rows_processed,
        "created": created_count,
        "updated": updated_count,
        "ignored": len(ignored_rows),
        "ignored_rows": ignored_rows,

        # IMPORTANT POUR LE FRONT + WORKFLOW
        "product_ids": product_ids,
        "total_products_to_scan": len(product_ids),

        "stock_movements_created": movements_created,
    }
       
@router.get("/pricing/pending")
def get_pending_pricing_products(db: Session = Depends(get_db)):
    return get_pending_pricing_products_service(db)


@router.get("/recommendations/elimination")
def get_elimination_recommendations(
    observation_days: int = 180,
    min_weekly_demand: float = 1.0,
    replacement_limit: int = 3,
    only_candidates: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return list_elimination_recommendations_service(
        db=db,
        observation_days=observation_days,
        min_weekly_demand=min_weekly_demand,
        replacement_limit=replacement_limit,
        only_candidates=only_candidates,
        limit=limit,
    )


@router.get("/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    return get_product_by_id_service(product_id, db)


@router.put("/{product_id}")
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    return update_product_service(product_id, payload, db)


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    return delete_product_service(product_id, db)


@router.get("/{product_id}/competitive-analysis-status")
def get_competitive_analysis_status(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    matched_count = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.produit_id == product_id, ProductCompetitor.statut_matching == "MATCHED")
        .count()
    )
    manual_review_count = (
        db.query(ProductCompetitor)
        .filter(ProductCompetitor.produit_id == product_id, ProductCompetitor.statut_matching == "MANUAL_REVIEW")
        .count()
    )

    return {
        "productId": product.id,
        "status": product.analyse_concurrentielle_statut,
        "date": product.analyse_concurrentielle_date,
        "statutPrix": getattr(product, "statut_prix", None),
        "matchedCompetitorProducts": matched_count,
        "manualReviewProducts": manual_review_count,
    }


@router.get("/{product_id}/pricing-details")
def get_product_pricing_details(product_id: int, db: Session = Depends(get_db)):
    return get_product_pricing_details_service(product_id, db)


@router.get("/{product_id}/stock-details")
def get_product_stock_details(product_id: int, db: Session = Depends(get_db)):
    return get_product_stock_details_service(product_id, db)


@router.get("/{product_id}/elimination-recommendation")
def get_product_elimination_recommendation(
    product_id: int,
    observation_days: int = 180,
    min_weekly_demand: float = 1.0,
    replacement_limit: int = 3,
    db: Session = Depends(get_db),
):
    return get_product_elimination_recommendation_service(
        product_id=product_id,
        db=db,
        observation_days=observation_days,
        min_weekly_demand=min_weekly_demand,
        replacement_limit=replacement_limit,
    )


@router.get("/{product_id}/kpis")
def get_product_kpis(product_id: int, days: int = 30, db: Session = Depends(get_db)):
    try:
        return get_product_kpis_service(product_id, db, days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur calcul KPI: {str(exc)}")


@router.put("/{product_id}/price")
def update_product_price(product_id: int, payload: ProductPriceUpdate, db: Session = Depends(get_db)):
    return update_product_price_service(
        product_id=product_id,
        new_price=payload.newPrixVente,
        justification=payload.justification,
        db=db,
    )


@router.post("/{product_id}/price/approve")
def approve_product_price(product_id: int, payload: PriceApprovalRequest, db: Session = Depends(get_db)):
    return approve_product_price_service(
        product_id=product_id,
        prix_valide=payload.prixValide,
        justification=payload.justification,
        db=db,
    )


@router.post("/{product_id}/initial-price-recommendation")
def get_initial_price_recommendation(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return calculate_price_recommendation(product_id=product.id, db=db)


@router.get("/{product_id}/price-recommendation")
def get_price_recommendation(product_id: int, strategy: str = "competitive", db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    if product.analyse_concurrentielle_statut == "RUNNING":
        return {
            "status": "pending",
            "productId": product.id,
            "message": "Analyse concurrentielle en cours. Réessayez dans quelques instants.",
        }

    blocked = _block_competitive_recommendation_if_validation_required(product, strategy, db)
    if blocked:
        return blocked

    return calculate_price_recommendation(product_id=product.id, db=db)


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
            "message": "Analyse concurrentielle en cours. Réessayez dans quelques instants.",
        }

    blocked = _block_competitive_recommendation_if_validation_required(product, strategy, db)
    if blocked:
        return blocked

    return calculate_price_recommendation(product_id=product.id, db=db)
