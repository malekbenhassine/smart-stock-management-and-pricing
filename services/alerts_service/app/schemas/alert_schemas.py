from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    alert_type: str = "GENERAL"
    priority: str = "MEDIUM"
    source_service: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    value: str | None = None
    threshold: str | None = None
    metadata: dict[str, Any] | None = None


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    message: str
    alert_type: str
    priority: str
    source_service: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    value: str | None = None
    threshold: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_read: bool
    created_at: datetime
    updated_at: datetime


class AlertListResponse(BaseModel):
    items: list[AlertRead]
    total: int
    unread: int


class MarkReadRequest(BaseModel):
    alert_ids: list[int]


class AlertSummary(BaseModel):
    total: int
    unread: int
    by_priority: dict[str, int]
    by_type: dict[str, int]
