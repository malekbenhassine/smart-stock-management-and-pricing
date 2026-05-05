from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from ..models.tables import SalesHistory


def bulk_upsert_sales_history(items, db: Session):
    """
    Import rapide de sales_history.

    Correction :
    - avant : SELECT ligne par ligne puis INSERT/UPDATE
    - maintenant : bulk upsert PostgreSQL
    - évite la saturation PostgreSQL pendant l'import des gros CSV
    """

    if not items:
        return {
            "status": "success",
            "message": "Aucune ligne à importer.",
            "rows": 0,
        }

    rows = []

    for item in items:
        rows.append(
            {
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
            }
        )

    stmt = insert(SalesHistory).values(rows)

    stmt = stmt.on_conflict_do_update(
        index_elements=["date", "store_id", "product_id"],
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

    return {
        "status": "success",
        "message": "Sales history importé avec succès.",
        "rows": len(rows),
    }


def fetch_sales_history(
    db: Session,
    product_id: Optional[str] = None,
    store_id: Optional[str] = None,
    category: Optional[str] = None,
    region: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 1000,
):
    """
    Récupère l'historique des ventes avec filtres optionnels.

    Cette fonction est utilisée par les routes API.
    Il ne faut pas la supprimer.
    """

    query = db.query(SalesHistory)

    if product_id:
        query = query.filter(SalesHistory.product_id == product_id)

    if store_id:
        query = query.filter(SalesHistory.store_id == store_id)

    if category:
        query = query.filter(SalesHistory.category == category)

    if region:
        query = query.filter(SalesHistory.region == region)

    if start_date:
        query = query.filter(SalesHistory.date >= start_date)

    if end_date:
        query = query.filter(SalesHistory.date <= end_date)

    return (
        query.order_by(SalesHistory.date.desc())
        .limit(limit)
        .all()
    )


def fetch_recent_product_history(
    product_id: str,
    db: Session,
    days: int = 30,
    limit: int = 1000,
):
    """
    Récupère l'historique récent d'un produit.

    Important :
    - product_id ici correspond souvent au SKU dans ton projet
    - utilisé par les endpoints de forecast/KPI/recommandation
    """

    if not product_id:
        return []

    max_date = (
        db.query(SalesHistory.date)
        .filter(SalesHistory.product_id == product_id)
        .order_by(SalesHistory.date.desc())
        .first()
    )

    if not max_date:
        return []

    last_date = max_date[0]
    start_date = last_date - timedelta(days=days)

    return (
        db.query(SalesHistory)
        .filter(SalesHistory.product_id == product_id)
        .filter(SalesHistory.date >= start_date)
        .filter(SalesHistory.date <= last_date)
        .order_by(SalesHistory.date.asc())
        .limit(limit)
        .all()
    )