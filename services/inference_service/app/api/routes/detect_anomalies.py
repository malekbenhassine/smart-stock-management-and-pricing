from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.anomaly_service import detect_anomalies_service

router = APIRouter(prefix="/detect", tags=["Anomalies"])


@router.get("/anomalies/{product_id}")
def detect_anomalies(product_id: int, db: Session = Depends(get_db)):
    return detect_anomalies_service(product_id, db)