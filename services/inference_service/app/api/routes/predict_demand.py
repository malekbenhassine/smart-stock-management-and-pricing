from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import date
from pydantic import BaseModel
from typing import Optional

from ...database import get_db, SalesHistory

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
    for item in items:
        obj = (
            db.query(SalesHistory)
            .filter(
                SalesHistory.date == item.date,
                SalesHistory.store_id == item.store_id,
                SalesHistory.product_id == item.product_id,
            )
            .first()
        )

        if not obj:
            obj = SalesHistory(
                date=item.date,
                store_id=item.store_id,
                product_id=item.product_id,
            )
            db.add(obj)

        obj.category = item.category
        obj.region = item.region
        obj.sales = item.units_sold
        obj.price = item.price
        obj.stock = item.inventory_level
        obj.discount = item.discount
        obj.competitor_pricing = item.competitor_pricing
        obj.units_ordered = item.units_ordered
        obj.weather_condition = item.weather_condition
        obj.holiday_promotion = item.holiday_promotion
        obj.seasonality = item.seasonality

    db.commit()
    return {"status": "success", "rows": len(items)}