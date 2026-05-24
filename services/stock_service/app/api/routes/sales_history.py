from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...schemas.schemas import SalesHistoryIn
from ...services.sales_history_service import (
    bulk_upsert_sales_history,
    fetch_sales_history,
    fetch_recent_product_history,
)

router = APIRouter(prefix="/sales-history", tags=["historique-ventes"])


@router.post("/bulk")
def bulk_sales_history(items: list[SalesHistoryIn], db: Session = Depends(get_db)):
    return bulk_upsert_sales_history(items, db)


@router.get("")
def get_sales_history(
    # Noms français officiels
    magasin_id: str | None = Query(default=None),
    produit_id: str | None = Query(default=None),
    date_cible: date | None = Query(default=None),
    nombre_jours: int = Query(default=90, ge=1, le=365),
    # Compatibilité anciennes requêtes/front/inference
    store_id: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    target_date: date | None = Query(default=None),
    n_days: int | None = Query(default=None, ge=1, le=365),
    db: Session = Depends(get_db),
):
    final_magasin_id = magasin_id or store_id
    final_produit_id = produit_id or product_id
    final_date_cible = date_cible or target_date
    final_nombre_jours = n_days or nombre_jours

    if not final_magasin_id or not final_produit_id or not final_date_cible:
        return []

    date_debut = final_date_cible - timedelta(days=final_nombre_jours)

    return fetch_sales_history(
        db=db,
        magasin_id=final_magasin_id,
        produit_id=final_produit_id,
        start_date=date_debut,
        end_date=final_date_cible,
        limit=final_nombre_jours + 10,
    )


@router.get("/recent")
def get_recent_history(
    # IMPORTANT : inference_service envoie encore product_id. On garde ce nom ici.
    product_id: str | None = Query(default=None),
    produit_id: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=365),
    limite: int | None = Query(default=None, ge=1, le=365),
    db: Session = Depends(get_db),
):
    final_product_id = product_id or produit_id
    final_limit = limite or limit

    if not final_product_id:
        return []

    return fetch_recent_product_history(
        db=db,
        product_id=final_product_id,
        limit=final_limit,
    )
