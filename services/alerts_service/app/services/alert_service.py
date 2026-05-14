from app.models.alert import Alert
from app.schemas.alert_schemas import AlertRead


def to_read(alert: Alert) -> AlertRead:
    return AlertRead(
        id=alert.id,
        title=alert.title,
        message=alert.message,
        alert_type=alert.alert_type,
        priority=alert.priority,
        source_service=alert.source_service,
        product_id=alert.product_id,
        product_name=alert.product_name,
        value=alert.value,
        threshold=alert.threshold,
        metadata=alert.metadata_json or {},
        is_read=alert.is_read,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )
