from typing import Any, Literal
from pydantic import BaseModel


class DashboardKpi(BaseModel):
    key: str
    label: str
    value: Any = None
    unit: str = ""
    delta: float | None = None
    trend: Literal["up", "down", "stable"] = "stable"
    status: Literal["good", "warning", "danger", "neutral"] = "neutral"
    description: str = ""


class DashboardResponse(BaseModel):
    filters: dict[str, Any]
    kpis: list[DashboardKpi]
    charts: dict[str, Any]
    tables: dict[str, Any]
    insights: list[dict[str, Any]]
    warnings: list[str] = []
    updated_at: str
