from datetime import date, timedelta
from sqlalchemy.orm import Session

from ..models.tables import SalesHistory


def bulk_upsert_sales_history(items, db: Session):
    count = 0

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

        count += 1

    db.commit()
    return {"status": "success", "rows": count}


def fetch_sales_history(
    db: Session,
    store_id: str,
    product_id: str,
    target_date: date,
    n_days: int = 90,
):
    start = target_date - timedelta(days=n_days)

    rows = (
        db.query(SalesHistory)
        .filter(
            SalesHistory.store_id == store_id,
            SalesHistory.product_id == product_id,
            SalesHistory.date >= start,
            SalesHistory.date < target_date,
        )
        .order_by(SalesHistory.date)
        .all()
    )

    return [
        {
            "date": r.date.isoformat(),
            "sales": r.sales,
            "price": r.price,
            "stock": r.stock,
            "discount": r.discount,
            "competitor_pricing": r.competitor_pricing,
            "units_ordered": r.units_ordered,
            "weather_condition": r.weather_condition,
            "holiday_promotion": r.holiday_promotion,
            "seasonality": r.seasonality,
            "category": r.category,
            "region": r.region,
        }
        for r in rows
    ]


def fetch_recent_product_history(db: Session, product_id: str, limit: int = 30):
    rows = (
        db.query(SalesHistory)
        .filter(SalesHistory.product_id == product_id)
        .order_by(SalesHistory.date.desc())
        .limit(limit)
        .all()
    )

    rows = list(reversed(rows))

    return [
        {
            "date": r.date.isoformat(),
            "sales": float(r.sales or 0.0),
            "price": float(r.price or 0.0),
            "stock": float(r.stock or 0.0) if r.stock is not None else 0.0,
            "discount": float(r.discount or 0.0),
            "category": r.category,
            "region": r.region,
        }
        for r in rows
    ]