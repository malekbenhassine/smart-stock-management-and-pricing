from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.schemas import StockMovementCreate, StockMovementUpdate
from app.services.stock_movement_service import (
    create_stock_movement_service,
    get_product_stock_movement_summary_service,
    list_stock_movements_service,
    update_stock_movement_service,
)

router = APIRouter(prefix="/stock-movements", tags=["stock-movements"])


@router.post("")
def create_stock_movement(
    payload: StockMovementCreate,
    db: Session = Depends(get_db),
):
    return create_stock_movement_service(payload, db)


@router.get("")
def list_stock_movements(
    produit_id: int | None = Query(default=None),
    type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_stock_movements_service(
        db=db,
        produit_id=produit_id,
        movement_type=type,
        limit=limit,
    )


@router.get("/products/{product_id}/summary")
def get_product_stock_movement_summary(
    product_id: int,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return get_product_stock_movement_summary_service(
        product_id=product_id,
        db=db,
        days=days,
    )


@router.put("/{movement_id}")
def update_stock_movement(
    movement_id: int,
    payload: StockMovementUpdate,
    db: Session = Depends(get_db),
):
    return update_stock_movement_service(
        movement_id=movement_id,
        payload=payload,
        db=db,
    )