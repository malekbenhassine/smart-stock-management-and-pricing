from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.promo_service import recommend_promo_service

router = APIRouter(prefix="/recommend", tags=["Promotion"])


@router.get("/promo/{product_id}")
def recommend_promo(product_id: int, db: Session = Depends(get_db)):
    return recommend_promo_service(product_id, db)