from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.services.kpi_service import get_product_kpis_service
from ...core.database import get_db
from ...models.tables import Product
from ...schemas.schemas import ProductIn, ProductCreate, ProductUpdate, ProductPriceUpdate
from ...services.product_service import (
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

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def get_products(q: str | None = None, db: Session = Depends(get_db)):
    return get_all_products(db, q)


@router.get("/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    return get_product_by_id_service(product_id, db)


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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur calcul KPI: {str(e)}")


@router.post("")
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    return create_product_service(payload, db)


@router.put("/{product_id}")
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    return update_product_service(product_id, payload, db)


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    return delete_product_service(product_id, db)


@router.post("/{product_id}/initial-price-recommendation")
def get_initial_price_recommendation(product_id: int, db: Session = Depends(get_db)):
    return calculate_initial_price_recommendation_service(product_id, db)


@router.put("/{product_id}/price")
def update_product_price(product_id: int, payload: ProductPriceUpdate, db: Session = Depends(get_db)):
    return update_product_price_service(
        product_id=product_id,
        new_price=payload.newPrixVente,
        justification=payload.justification,
        db=db,
    )


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