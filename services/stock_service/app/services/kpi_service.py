from datetime import timedelta
from sqlalchemy.orm import Session

from app.models.tables import Product, SalesHistory


def get_product_kpis_service(product_id: int, db: Session, days: int = 30) -> dict:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise ValueError(f"Produit introuvable avec id={product_id}")

    if not product.sku:
        raise ValueError("Le produit n'a pas de SKU, impossible de calculer les KPI.")

    # Dernière date disponible pour ce SKU
    latest_row = (
        db.query(SalesHistory)
        .filter(SalesHistory.product_id == product.sku)
        .order_by(SalesHistory.date.desc())
        .first()
    )

    # Aucun historique pour ce SKU
    if not latest_row or not latest_row.date:
        return {
            "product_id": product.id,
            "sku": product.sku,
            "name": product.nom,
            "period_days": days,
            "quantity_sold": 0,
            "avg_daily_sales": 0,
            "avg_stock": float(product.stock_disponible or 0),
            "stock_rotation": 0,
            "stock_coverage_days": None,
            "current_stock": float(product.stock_disponible or 0),
            "history_rows_count": 0,
            "matching_mode": "sku",
        }

    end_date = latest_row.date
    start_date = end_date - timedelta(days=days)

    history_rows = (
        db.query(SalesHistory)
        .filter(SalesHistory.product_id == product.sku)
        .filter(SalesHistory.date >= start_date)
        .filter(SalesHistory.date <= end_date)
        .order_by(SalesHistory.date.asc())
        .all()
    )

    # sales = quantité vendue
    quantity_sold = sum(float(row.sales or 0) for row in history_rows)

    # vitesse de vente moyenne par jour
    avg_daily_sales = quantity_sold / days if days > 0 else 0.0

    # stock = niveau de stock historique
    stock_values = [
        float(row.stock or 0)
        for row in history_rows
        if row.stock is not None
    ]

    avg_stock = (
        sum(stock_values) / len(stock_values)
        if stock_values
        else float(product.stock_disponible or 0)
    )

    # rotation = ventes / stock moyen
    stock_rotation = quantity_sold / avg_stock if avg_stock > 0 else 0.0

    current_stock = float(product.stock_disponible or 0)

    # couverture = stock actuel / vitesse de vente
    stock_coverage_days = current_stock / avg_daily_sales if avg_daily_sales > 0 else None

    return {
        "product_id": product.id,
        "sku": product.sku,
        "name": product.nom,
        "period_days": days,
        "quantity_sold": round(quantity_sold, 2),
        "avg_daily_sales": round(avg_daily_sales, 2),
        "avg_stock": round(avg_stock, 2),
        "stock_rotation": round(stock_rotation, 2),
        "stock_coverage_days": round(stock_coverage_days, 2) if stock_coverage_days is not None else None,
        "current_stock": round(current_stock, 2),
        "history_rows_count": len(history_rows),
        "matching_mode": "sku",
        "analysis_start_date": str(start_date),
        "analysis_end_date": str(end_date),
    }
    
#rotation = quantité vendue / stock moyen    