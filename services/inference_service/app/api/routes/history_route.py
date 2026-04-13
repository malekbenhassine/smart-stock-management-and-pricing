from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from pydantic import BaseModel
from typing import Optional
from datetime import date

from app.database import get_db, SalesHistory

router = APIRouter(prefix="/history", tags=["history"])


class SalesHistoryIn(BaseModel):
    date: date
    store_id: str
    product_id: str
    category: Optional[str] = None
    region: Optional[str] = None
    units_sold: float
    price: float
    inventory_level: Optional[float] = None
    discount: Optional[float] = None
    competitor_pricing: Optional[float] = None
    units_ordered: Optional[float] = None
    weather_condition: Optional[str] = None
    holiday_promotion: Optional[int] = None
    seasonality: Optional[str] = None


@router.post("/bulk")
def bulk_history(items: list[SalesHistoryIn], db: Session = Depends(get_db)):
    if not items:
        return {"status": "success", "rows": 0}

    rows = []
    for item in items:
        rows.append({
            "date": item.date,
            "store_id": item.store_id,
            "product_id": item.product_id,
            "category": item.category,
            "region": item.region,
            "sales": item.units_sold,
            "price": item.price,
            "stock": item.inventory_level,
            "discount": item.discount,
            "competitor_pricing": item.competitor_pricing,
            "units_ordered": item.units_ordered,
            "weather_condition": item.weather_condition,
            "holiday_promotion": item.holiday_promotion,
            "seasonality": item.seasonality,
        })

    stmt = insert(SalesHistory).values(rows)

    stmt = stmt.on_conflict_do_update(
        constraint="uq_sales_history_date_store_product",
        set_={
            "category": stmt.excluded.category,
            "region": stmt.excluded.region,
            "sales": stmt.excluded.sales,
            "price": stmt.excluded.price,
            "stock": stmt.excluded.stock,
            "discount": stmt.excluded.discount,
            "competitor_pricing": stmt.excluded.competitor_pricing,
            "units_ordered": stmt.excluded.units_ordered,
            "weather_condition": stmt.excluded.weather_condition,
            "holiday_promotion": stmt.excluded.holiday_promotion,
            "seasonality": stmt.excluded.seasonality,
        },
    )

    db.execute(stmt)
    db.commit()

    return {"status": "success", "rows": len(rows)}