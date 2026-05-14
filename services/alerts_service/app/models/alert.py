from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    alert_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="GENERAL")
    priority: Mapped[str] = mapped_column(String(30), index=True, nullable=False, default="MEDIUM")
    source_service: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)

    product_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    threshold: Mapped[str | None] = mapped_column(String(100), nullable=True)

    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True, default=dict)

    is_read: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
