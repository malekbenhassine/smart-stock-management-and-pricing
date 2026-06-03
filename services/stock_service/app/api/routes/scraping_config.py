from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tables import ScrapingCatalogFrequencyConfig


router = APIRouter(
    prefix="/internal/scraping-config",
    tags=["internal-scraping-config"],
)

LEGACY_CATALOG_INTERVAL_MINUTES = 1440
CONFIG_ID = 1


class CatalogFrequencyConfigPayload(BaseModel):
    enabled: bool = False
    # Conservé uniquement pour compatibilité avec l'ancien front.
    # La fréquence réelle est définie par concurrent : 6h, 12h ou 24h.
    interval_minutes: int = Field(default=LEGACY_CATALOG_INTERVAL_MINUTES, ge=1)
    competitor_id: int | None = None
    next_run_at: datetime | None = None


def _get_or_create_config(db: Session) -> ScrapingCatalogFrequencyConfig:
    config = (
        db.query(ScrapingCatalogFrequencyConfig)
        .filter(ScrapingCatalogFrequencyConfig.id == CONFIG_ID)
        .first()
    )

    if config:
        return config

    config = ScrapingCatalogFrequencyConfig(
        id=CONFIG_ID,
        enabled=False,
        interval_minutes=LEGACY_CATALOG_INTERVAL_MINUTES,
        competitor_id=None,
        next_run_at=None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _to_dict(config: ScrapingCatalogFrequencyConfig) -> dict:
    return {
        "id": config.id,
        "enabled": bool(config.enabled),
        "interval_minutes": int(config.interval_minutes or LEGACY_CATALOG_INTERVAL_MINUTES),
        "competitor_id": config.competitor_id,
        "next_run_at": config.next_run_at.isoformat(timespec="seconds") if config.next_run_at else None,
        "updated_at": config.updated_at.isoformat(timespec="seconds") if config.updated_at else None,
    }


@router.get("/catalog-frequency")
def get_catalog_frequency_config(db: Session = Depends(get_db)):
    config = _get_or_create_config(db)
    return _to_dict(config)


@router.put("/catalog-frequency")
def update_catalog_frequency_config(
    payload: CatalogFrequencyConfigPayload,
    db: Session = Depends(get_db),
):
    config = _get_or_create_config(db)

    config.enabled = bool(payload.enabled)
    config.interval_minutes = int(payload.interval_minutes or LEGACY_CATALOG_INTERVAL_MINUTES)
    config.competitor_id = payload.competitor_id
    config.next_run_at = payload.next_run_at
    config.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(config)
    return _to_dict(config)
