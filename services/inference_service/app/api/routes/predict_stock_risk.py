from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.stock_risk_service import predict_stock_risk_service

router = APIRouter(prefix="/predict", tags=["Stock Risk"])


@router.get("/stock-risk/{product_id}")
def predict_stock_risk(product_id: int, db: Session = Depends(get_db)):
    return predict_stock_risk_service(product_id, db)