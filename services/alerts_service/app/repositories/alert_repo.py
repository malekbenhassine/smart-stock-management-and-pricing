from collections import Counter
from typing import Optional,List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.schemas.alert_schemas import AlertCreate


class AlertRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: AlertCreate) -> Alert:
        alert = Alert(
            title=payload.title,
            message=payload.message,
            alert_type=(payload.alert_type or "GENERAL").upper(),
            priority=(payload.priority or "MEDIUM").upper(),
            source_service=payload.source_service,
            product_id=payload.product_id,
            product_name=payload.product_name,
            value=payload.value,
            threshold=payload.threshold,
            metadata_json=payload.metadata or {},
        )
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def list(self, *, priority: Optional[str] = None, alert_type: Optional[str] = None, is_read: Optional[bool] = None, limit: int = 100, offset: int = 0):
        stmt = select(Alert)
        count_stmt = select(func.count(Alert.id))
        unread_stmt = select(func.count(Alert.id)).where(Alert.is_read.is_(False))

        filters = []
        if priority:
            filters.append(Alert.priority == priority.upper())
        if alert_type:
            filters.append(Alert.alert_type == alert_type.upper())
        if is_read is not None:
            filters.append(Alert.is_read.is_(is_read))

        for f in filters:
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)

        stmt = stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
        items = self.db.scalars(stmt).all()
        total = self.db.scalar(count_stmt) or 0
        unread = self.db.scalar(unread_stmt) or 0
        return items, total, unread

    def get(self, alert_id: int) -> Alert | None:
        return self.db.get(Alert, alert_id)

    def mark_read(self, alert_ids: List[int]) -> int:
        if not alert_ids:
            return 0
        items = self.db.scalars(select(Alert).where(Alert.id.in_(alert_ids))).all()
        for alert in items:
            alert.is_read = True
        self.db.commit()
        return len(items)

    def mark_all_read(self) -> int:
        items = self.db.scalars(select(Alert).where(Alert.is_read.is_(False))).all()
        for alert in items:
            alert.is_read = True
        self.db.commit()
        return len(items)

    def delete(self, alert_id: int) -> bool:
        alert = self.get(alert_id)
        if not alert:
            return False
        self.db.delete(alert)
        self.db.commit()
        return True

    def summary(self):
        items = self.db.scalars(select(Alert)).all()
        return {
            "total": len(items),
            "unread": sum(1 for item in items if not item.is_read),
            "by_priority": dict(Counter(item.priority for item in items)),
            "by_type": dict(Counter(item.alert_type for item in items)),
        }
