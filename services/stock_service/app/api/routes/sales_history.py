from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...schemas.schemas import SalesHistoryIn
from ...services.sales_history_service import (
    bulk_upsert_sales_history,
    fetch_sales_history,
    fetch_recent_product_history,
)

router = APIRouter(prefix="/sales-history", tags=["sales-history"])


@router.post("/bulk")
def bulk_sales_history(items: list[SalesHistoryIn], db: Session = Depends(get_db)):
    return bulk_upsert_sales_history(items, db)


@router.get("")
def get_sales_history(
    store_id: str = Query(...),
    product_id: str = Query(...),
    target_date: date = Query(...),
    n_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return fetch_sales_history(
        db=db,
        store_id=store_id,
        product_id=product_id,
        target_date=target_date,
        n_days=n_days,
    )


@router.get("/recent")
def get_recent_history(
    product_id: str = Query(...),
    limit: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return fetch_recent_product_history(db=db, product_id=product_id, limit=limit)