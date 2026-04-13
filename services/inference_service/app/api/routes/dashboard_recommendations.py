from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.dashboard_service import dashboard_recommendations_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/recommendations")
def dashboard_recommendations(db: Session = Depends(get_db)):
    return dashboard_recommendations_service(db)