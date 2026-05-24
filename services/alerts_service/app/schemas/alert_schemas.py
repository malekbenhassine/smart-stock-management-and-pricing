from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AlertCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    alert_type: str = "GENERAL"
    priority: str = "MEDIUM"
    source_service: Optional[str] = None

    recipient_user_id: Optional[int] = None
    target_role: Optional[str] = None
    broadcast: bool = False

    product_id: Optional[int] = None
    product_name: Optional[str] = None
    value: Optional[str] = None
    threshold: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class AlertEventCreate(BaseModel):
    event_type: str = Field(..., min_length=1)
    source_service: str = "unknown_service"
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    target_role: Optional[str] = None
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    value: Optional[float | int | str] = None
    threshold: Optional[float | int | str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    message: str
    alert_type: str
    priority: str
    source_service: Optional[str] = None

    recipient_user_id: Optional[int] = None
    target_role: Optional[str] = None
    broadcast: bool = False

    product_id: Optional[int] = None
    product_name: Optional[str] = None
    value: Optional[str] = None
    threshold: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_read: bool
    created_at: datetime
    updated_at: datetime


class AlertListResponse(BaseModel):
    items: List[AlertRead]
    total: int
    unread: int


class MarkReadRequest(BaseModel):
    alert_ids: List[int]


class AlertSummary(BaseModel):
    total: int
    unread: int
    by_priority: dict[str, int]
    by_type: dict[str, int]


class ScanStockResponse(BaseModel):
    created: int
    details: dict[str, int]
