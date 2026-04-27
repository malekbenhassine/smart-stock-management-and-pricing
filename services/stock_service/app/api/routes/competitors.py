from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.competitor_schemas import (
    CompetitorCreate,
    CompetitorUpdate,
    CompetitorAdvancedConfigUpdate,
    CompetitorCatalogSelectionUpdate,
)
from app.services.competitor_service import (
    create_competitor_service,
    list_competitors_service,
    get_competitor_by_id_service,
    update_competitor_service,
    update_advanced_config_service,
    due_competitors_service,
    update_last_scraping_service,
    replace_catalog_selection_service,
)

router = APIRouter(tags=["competitors"])


@router.get("/competitors/due")
def get_due_competitors(db: Session = Depends(get_db)):
    return due_competitors_service(db)


@router.get("/competitors")
def list_competitors(db: Session = Depends(get_db)):
    return list_competitors_service(db)


@router.get("/competitors/{competitor_id}")
def get_competitor_by_id(competitor_id: int, db: Session = Depends(get_db)):
    try:
        return get_competitor_by_id_service(competitor_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/competitors")
def create_competitor(payload: CompetitorCreate, db: Session = Depends(get_db)):
    try:
        return create_competitor_service(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/competitors/{competitor_id}")
def update_competitor(competitor_id: int, payload: CompetitorUpdate, db: Session = Depends(get_db)):
    try:
        return update_competitor_service(competitor_id, payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/competitors/{competitor_id}/advanced-config")
def update_advanced_config(
    competitor_id: int,
    payload: CompetitorAdvancedConfigUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_advanced_config_service(competitor_id, payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/competitors/{competitor_id}/catalog-selection")
def update_catalog_selection(
    competitor_id: int,
    payload: CompetitorCatalogSelectionUpdate,
    db: Session = Depends(get_db),
):
    try:
        return replace_catalog_selection_service(competitor_id, payload.catalog_ids, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/competitors/{competitor_id}/last-scraping")
def update_last_scraping(competitor_id: int, db: Session = Depends(get_db)):
    try:
        return update_last_scraping_service(competitor_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))