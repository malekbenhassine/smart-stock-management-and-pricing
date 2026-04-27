from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse
from sqlalchemy.orm import Session

from app.models.tables import Competitor, CompetitorCatalog
from app.schemas.competitor_schemas import (
    CompetitorCreate,
    CompetitorUpdate,
    CompetitorAdvancedConfigUpdate,
)
from app.services.scraping_client import ScrapingServiceClient


def normalize_site_url(raw_url: str) -> tuple[str, str]:
    parsed = urlparse(str(raw_url).strip())
    scheme = parsed.scheme or "https"
    host = (parsed.netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]

    normalized = urlunparse((scheme, host, "/", "", "", ""))
    return normalized, host


def normalize_catalog_url(raw_url: str) -> str:
    parsed = urlparse(str(raw_url).strip())
    scheme = parsed.scheme or "https"
    host = (parsed.netloc or "").lower().strip()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, host, path, "", "", ""))


def _serialize_catalog(c: CompetitorCatalog) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "url": c.url,
        "parent_url": c.parent_url,
        "depth": c.depth,
        "score": c.score,
        "source": c.source,
        "is_selected": c.is_selected,
        "is_active": c.is_active,
    }


def _serialize_competitor(obj: Competitor) -> dict:
    return {
        "id": obj.id,
        "nom": obj.nom,
        "site_url": obj.site_url,
        "site_host_normalized": obj.site_host_normalized,
        "actif": obj.actif,
        "frequence_scraping_heures": obj.frequence_scraping_heures,
        "dernier_scraping": obj.dernier_scraping.isoformat() if obj.dernier_scraping else None,
        "discovery_status": obj.discovery_status,
        "last_discovery_at": obj.last_discovery_at.isoformat() if obj.last_discovery_at else None,
        "last_discovery_error": obj.last_discovery_error,
        "auto_keywords": obj.auto_keywords_json or [],
        "selectors_override": obj.selectors_override_json or {},
        "catalogs": [_serialize_catalog(c) for c in obj.catalogs if c.is_active],
    }


def _replace_catalogs(competitor: Competitor, discovered_catalogs: list[dict], db: Session) -> None:
    db.query(CompetitorCatalog).filter(
        CompetitorCatalog.competitor_id == competitor.id
    ).delete()

    for item in discovered_catalogs:
        url = normalize_catalog_url(item["url"])
        row = CompetitorCatalog(
            competitor_id=competitor.id,
            title=item["title"],
            url=url,
            url_key=url,
            parent_url=item.get("parent_url"),
            depth=item.get("depth", 0),
            score=float(item.get("score", 0)),
            source=item.get("source", "auto_discovery"),
            is_selected=bool(item.get("is_selected", True)),
            is_active=True,
        )
        db.add(row)


def create_competitor_service(payload: CompetitorCreate, db: Session):
    normalized_site_url, site_host = normalize_site_url(str(payload.site_url))

    existing = db.query(Competitor).filter(
        Competitor.site_host_normalized == site_host
    ).first()
    if existing:
        raise ValueError("Un concurrent existe déjà pour ce site")

    obj = Competitor(
        nom=payload.nom.strip(),
        site_url=normalized_site_url,
        site_host_normalized=site_host,
        actif=payload.actif,
        frequence_scraping_heures=payload.frequence_scraping_heures,
        discovery_status="pending",
        auto_keywords_json=[],
        selectors_override_json={},
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    scraper = ScrapingServiceClient()

    try:
        discovery = scraper.discover_site(
            competitor_name=obj.nom,
            site_url=obj.site_url,
        )

        _replace_catalogs(obj, discovery.get("catalogs", []), db)
        obj.auto_keywords_json = discovery.get("keywords", [])
        obj.discovery_status = "ready"
        obj.last_discovery_at = datetime.utcnow()
        obj.last_discovery_error = None

        db.commit()
        db.refresh(obj)

    except Exception as exc:
        obj.discovery_status = "partial"
        obj.last_discovery_at = datetime.utcnow()
        obj.last_discovery_error = str(exc)
        db.commit()
        db.refresh(obj)

    return _serialize_competitor(obj)


def list_competitors_service(db: Session):
    rows = db.query(Competitor).order_by(Competitor.id.desc()).all()
    return [_serialize_competitor(c) for c in rows]


def get_competitor_by_id_service(competitor_id: int, db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")
    return _serialize_competitor(obj)


def update_competitor_service(competitor_id: int, payload: CompetitorUpdate, db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    site_changed = False

    if payload.nom is not None:
        obj.nom = payload.nom.strip()

    if payload.actif is not None:
        obj.actif = payload.actif

    if payload.frequence_scraping_heures is not None:
        obj.frequence_scraping_heures = payload.frequence_scraping_heures

    if payload.site_url is not None:
        normalized_site_url, site_host = normalize_site_url(str(payload.site_url))
        duplicate = db.query(Competitor).filter(
            Competitor.site_host_normalized == site_host,
            Competitor.id != obj.id
        ).first()
        if duplicate:
            raise ValueError("Un autre concurrent existe déjà pour ce site")

        obj.site_url = normalized_site_url
        obj.site_host_normalized = site_host
        site_changed = True

    if site_changed:
        obj.discovery_status = "pending"

    db.commit()
    db.refresh(obj)
    return _serialize_competitor(obj)


def update_advanced_config_service(
    competitor_id: int,
    payload: CompetitorAdvancedConfigUpdate,
    db: Session,
):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    if payload.selectors_override is not None:
        obj.selectors_override_json = payload.selectors_override

    db.commit()
    db.refresh(obj)
    return _serialize_competitor(obj)


def due_competitors_service(db: Session):
    rows = db.query(Competitor).filter(
        Competitor.actif.is_(True),
        Competitor.discovery_status.in_(["ready", "partial"])
    ).all()

    now = datetime.utcnow()
    due = []

    for c in rows:
        if c.dernier_scraping is None:
            due.append(_serialize_competitor(c))
            continue

        next_time = c.dernier_scraping + timedelta(hours=c.frequence_scraping_heures or 24)
        if next_time <= now:
            due.append(_serialize_competitor(c))

    return due


def update_last_scraping_service(competitor_id: int, db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    obj.dernier_scraping = datetime.utcnow()
    db.commit()

    return {
        "status": "updated",
        "competitor_id": competitor_id,
        "dernier_scraping": obj.dernier_scraping.isoformat(),
    }


def replace_catalog_selection_service(competitor_id: int, catalog_ids: list[int], db: Session):
    obj = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    if not obj:
        raise ValueError("Concurrent introuvable")

    catalogs = db.query(CompetitorCatalog).filter(
        CompetitorCatalog.competitor_id == competitor_id
    ).all()

    selected_set = set(catalog_ids)
    for c in catalogs:
        c.is_selected = c.id in selected_set

    db.commit()
    db.refresh(obj)
    return _serialize_competitor(obj)