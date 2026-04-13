from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.stock_details_service import get_stock_details_service

router = APIRouter(prefix="/products", tags=["Stock Details"])


@router.get("/{product_id}/stock-details")
def get_stock_details(product_id: int, db: Session = Depends(get_db)):
    return get_stock_details_service(product_id, db)