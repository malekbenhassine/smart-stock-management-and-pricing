from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.repositories.alert_repo import AlertRepository
from app.schemas.alert_schemas import AlertCreate, AlertListResponse, AlertRead, AlertSummary, MarkReadRequest
from app.services.alert_service import to_read

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("", response_model=AlertRead, status_code=201)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    alert = AlertRepository(db).create(payload)
    return to_read(alert)


@router.get("", response_model=AlertListResponse)
def list_alerts(
    priority: str | None = None,
    alert_type: str | None = None,
    is_read: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, unread = AlertRepository(db).list(
        priority=priority,
        alert_type=alert_type,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )
    return AlertListResponse(items=[to_read(item) for item in items], total=total, unread=unread)


@router.get("/summary", response_model=AlertSummary)
def alert_summary(db: Session = Depends(get_db)):
    return AlertRepository(db).summary()


@router.patch("/read")
def mark_read(payload: MarkReadRequest, db: Session = Depends(get_db)):
    updated = AlertRepository(db).mark_read(payload.alert_ids)
    return {"updated": updated}


@router.patch("/read-all")
def mark_all_read(db: Session = Depends(get_db)):
    updated = AlertRepository(db).mark_all_read()
    return {"updated": updated}


@router.delete("/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    ok = AlertRepository(db).delete(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    return {"deleted": True}
