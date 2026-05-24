from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.alert import Alert
from app.schemas.alert_schemas import (
    AlertCreate,
    AlertEventCreate,
    AlertListResponse,
    AlertRead,
    AlertSummary,
    MarkReadRequest,
    ScanStockResponse,
)
from app.services.alert_service import to_read
from app.services.event_alert_service import alerts_from_event
from app.services.stock_rule_service import StockRuleService

router = APIRouter(prefix="/alerts", tags=["alerts"])


REPEATABLE_ALERT_TYPES = {
    "CSV_IMPORT_SUCCESS",
    "CSV_IMPORT_FAILED",
    "SCRAPING_SUCCESS",
    "SCRAPING_FAILED",
    "SCRAPING_ERROR",
    "COMPETITOR_PRODUCT_TO_VALIDATE",
    "COMPETITOR_CREATED",
    "COMPETITOR_CATALOGS_READY",
    "COMPETITOR_CATALOGS_PARTIAL",
    "COMPETITOR_CATALOGS_FAILED",

    "ACCOUNT_CREATED",
    "ACCOUNT_ACTIVATED",
    "PASSWORD_CHANGED",
    "PASSWORD_RESET",
    "AUTH_FAILED",
    "PRICE_RECOMMENDATION_AVAILABLE",
    "PRICE_CHANGE_REQUEST_APPROVED",
    "PRICE_CHANGE_REQUEST_REJECTED",
}


def parse_roles(target_roles: str | None) -> list[str]:
    if not target_roles:
        return []
    return [role.strip().upper() for role in target_roles.split(",") if role.strip()]


def normalize_role(role: str | None) -> str | None:
    return role.upper() if role else None


def normalize_priority(priority: str | None) -> str:
    value = (priority or "MEDIUM").upper()
    if value == "IMPORTANT":
        return "HIGH"
    if value not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
        return "MEDIUM"
    return value


def allow_repeat_alert(payload: AlertCreate) -> bool:
    return (payload.alert_type or "").upper() in REPEATABLE_ALERT_TYPES


def build_alert(payload: AlertCreate) -> Alert:
    return Alert(
        title=payload.title,
        message=payload.message,
        alert_type=(payload.alert_type or "GENERAL").upper(),
        priority=normalize_priority(payload.priority),
        source_service=payload.source_service,
        recipient_user_id=payload.recipient_user_id,
        target_role=normalize_role(payload.target_role),
        broadcast=bool(payload.broadcast),
        product_id=payload.product_id,
        product_name=payload.product_name,
        value=str(payload.value) if payload.value is not None else None,
        threshold=str(payload.threshold) if payload.threshold is not None else None,
        metadata_json=payload.metadata or {},
    )


def exists_active_alert(db: Session, payload: AlertCreate) -> bool:
    target_role = normalize_role(payload.target_role)

    stmt = select(Alert.id).where(
        Alert.alert_type == (payload.alert_type or "GENERAL").upper(),
        Alert.source_service == payload.source_service,
        Alert.broadcast.is_(bool(payload.broadcast)),
    )

    if payload.product_id is None:
        stmt = stmt.where(Alert.product_id.is_(None))
    else:
        stmt = stmt.where(Alert.product_id == payload.product_id)

    if payload.recipient_user_id is None:
        stmt = stmt.where(Alert.recipient_user_id.is_(None))
    else:
        stmt = stmt.where(Alert.recipient_user_id == payload.recipient_user_id)

    if target_role is None:
        stmt = stmt.where(Alert.target_role.is_(None))
    else:
        stmt = stmt.where(Alert.target_role == target_role)

    return db.scalar(stmt.limit(1)) is not None


def create_one_alert(db: Session, payload: AlertCreate) -> Alert | None:
    if not allow_repeat_alert(payload):
        if exists_active_alert(db, payload):
            return None

    alert = build_alert(payload)
    db.add(alert)
    db.commit()
    db.refresh(alert)

    return alert


def create_many_alerts(db: Session, payloads: List[AlertCreate]) -> List[Alert]:
    created: List[Alert] = []
    seen_keys = set()

    for payload in payloads:
        alert_type = (payload.alert_type or "GENERAL").upper()

        key = (
            alert_type,
            payload.source_service,
            payload.product_id,
            payload.recipient_user_id,
            normalize_role(payload.target_role),
            bool(payload.broadcast),
        )

        if key in seen_keys:
            continue

        seen_keys.add(key)

        if not allow_repeat_alert(payload):
            if exists_active_alert(db, payload):
                continue

        created.append(build_alert(payload))

    if created:
        db.add_all(created)
        db.commit()

        for item in created:
            db.refresh(item)

    return created


def visibility_filters(user_id: int | None, roles: List[str] | None):
    roles = [str(role).upper() for role in roles or [] if role]

    filters = [Alert.broadcast.is_(True)]

    if user_id is not None:
        filters.append(Alert.recipient_user_id == user_id)

    if roles:
        filters.append(Alert.target_role.in_(roles))

    return or_(*filters)


def dedupe_visible_alerts(items: List[Alert], user_id: int | None = None) -> List[Alert]:
    seen = set()
    result: List[Alert] = []

    for alert in items:
        meta = alert.metadata_json or {}

        # Cas spécial CSV :
        # Si le manager est aussi l'utilisateur qui a lancé l'import,
        # il voit techniquement :
        # 1) l'alerte user_id
        # 2) l'alerte ROLE_MANAGER
        #
        # On masque donc l'alerte ROLE_MANAGER pour celui qui a lancé l'import.
        if (
            user_id is not None
            and alert.alert_type in {"CSV_IMPORT_SUCCESS", "CSV_IMPORT_FAILED"}
            and alert.target_role == "MANAGER"
            and meta.get("event_user_id") == user_id
        ):
            continue

        if alert.alert_type in {"CSV_IMPORT_SUCCESS", "CSV_IMPORT_FAILED"}:
            key = (
                alert.alert_type,
                alert.source_service,
                alert.value,
                meta.get("filename"),
                meta.get("table"),
                meta.get("rows_imported"),
                meta.get("rows_count"),
                meta.get("event_user_id"),
            )
        else:
            key = (
                alert.alert_type,
                alert.source_service,
                alert.value,
                alert.threshold,
                alert.product_id,
                alert.product_name,
                meta.get("event_type"),
                meta.get("event_user_id"),
            )

        if key in seen:
            continue

        seen.add(key)
        result.append(alert)

    return result

@router.post("", response_model=AlertRead, status_code=201)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    alert = create_one_alert(db, payload)

    if not alert:
        raise HTTPException(status_code=409, detail="Alerte déjà existante")

    return to_read(alert)


@router.post("/events", status_code=201)
def create_alerts_from_event(payload: AlertEventCreate, db: Session = Depends(get_db)):
    alerts = create_many_alerts(db, alerts_from_event(payload))

    return {
        "created": len(alerts),
        "items": [to_read(alert) for alert in alerts],
    }


@router.post("/scan-stock-rules", response_model=ScanStockResponse)
def scan_stock_rules(db: Session = Depends(get_db)):
    try:
        service = StockRuleService()
        payloads = service.generate_alerts()
        created = create_many_alerts(db, payloads)

        return ScanStockResponse(
            created=len(created),
            details=getattr(service, "last_details", {}),
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("", response_model=AlertListResponse)
def list_alerts(
    user_id: int | None = None,
    target_roles: str | None = None,
    priority: str | None = None,
    alert_type: str | None = None,
    is_read: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    roles = parse_roles(target_roles)
    visibility = visibility_filters(user_id, roles)

    stmt = select(Alert).where(visibility)

    if priority:
        stmt = stmt.where(Alert.priority == priority.upper())

    if alert_type:
        stmt = stmt.where(Alert.alert_type == alert_type.upper())

    if is_read is not None:
        stmt = stmt.where(Alert.is_read.is_(is_read))

    raw_items = db.scalars(
        stmt.order_by(Alert.created_at.desc())
    ).all()

    deduped_items = dedupe_visible_alerts(raw_items, user_id=user_id)

    total = len(deduped_items)
    unread = sum(1 for item in deduped_items if not item.is_read)

    items = deduped_items[offset: offset + limit]

    return AlertListResponse(
        items=[to_read(item) for item in items],
        total=total,
        unread=unread,
    )


@router.get("/summary", response_model=AlertSummary)
def alert_summary(
    user_id: int | None = None,
    target_roles: str | None = None,
    db: Session = Depends(get_db),
):
    roles = parse_roles(target_roles)
    visibility = visibility_filters(user_id, roles)

    raw_items = db.scalars(
        select(Alert)
        .where(visibility)
        .order_by(Alert.created_at.desc())
    ).all()

    items = dedupe_visible_alerts(raw_items, user_id=user_id)

    return {
        "total": len(items),
        "unread": sum(1 for item in items if not item.is_read),
        "by_priority": dict(Counter(item.priority for item in items)),
        "by_type": dict(Counter(item.alert_type for item in items)),
    }


@router.patch("/read")
def mark_read(
    payload: MarkReadRequest,
    user_id: int | None = None,
    target_roles: str | None = None,
    db: Session = Depends(get_db),
):
    if not payload.alert_ids:
        return {"updated": 0}

    roles = parse_roles(target_roles)

    items = db.scalars(
        select(Alert).where(
            Alert.id.in_(payload.alert_ids),
            visibility_filters(user_id, roles),
        )
    ).all()

    for alert in items:
        alert.is_read = True

    db.commit()

    return {"updated": len(items)}


@router.patch("/read-all")
def mark_all_read(
    user_id: int | None = None,
    target_roles: str | None = None,
    db: Session = Depends(get_db),
):
    roles = parse_roles(target_roles)

    items = db.scalars(
        select(Alert).where(
            visibility_filters(user_id, roles),
            Alert.is_read.is_(False),
        )
    ).all()

    for alert in items:
        alert.is_read = True

    db.commit()

    return {"updated": len(items)}


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: int,
    user_id: int | None = None,
    target_roles: str | None = None,
    db: Session = Depends(get_db),
):
    roles = parse_roles(target_roles)

    alert = db.scalar(
        select(Alert).where(
            Alert.id == alert_id,
            visibility_filters(user_id, roles),
        )
    )

    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")

    db.delete(alert)
    db.commit()

    return {"deleted": True}