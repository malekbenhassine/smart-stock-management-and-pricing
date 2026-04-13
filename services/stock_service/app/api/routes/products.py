from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models.tables import Product
from ...schemas.schemas import ProductIn
from ...services.product_service import (
    get_all_products,
    get_product_by_id_service,
    get_product_pricing_details_service,
    get_product_stock_details_service,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def get_products(
    q: str | None = Query(default=None, description="Recherche par nom, SKU, marque ou catégorie"),
    limit: int = Query(default=100, ge=1, le=500),
):
    return get_all_products(q=q, limit=limit)


@router.get("/{product_id}")
def get_product_by_id(product_id: int):
    return get_product_by_id_service(product_id)


@router.get("/{product_id}/pricing-details")
def get_product_pricing_details(product_id: int):
    return get_product_pricing_details_service(product_id)


@router.get("/{product_id}/stock-details")
def get_product_stock_details(product_id: int):
    return get_product_stock_details_service(product_id)


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
    return {"status": "success", "rows": count}