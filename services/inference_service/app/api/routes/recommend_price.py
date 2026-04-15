from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.stock_client import get_product_from_stock_service
from app.services.request_builder import build_request_from_product
from app.services.price_service import (
    recommend_price_service,
    build_price_recommendation_response,
)

router = APIRouter(prefix="/recommend")


@router.get("/price/{product_id}")
def recommend_price(product_id: int, db: Session = Depends(get_db)):
    product = get_product_from_stock_service(product_id)
    req = build_request_from_product(product)
    result = recommend_price_service(req, db)

    return build_price_recommendation_response(product, result)