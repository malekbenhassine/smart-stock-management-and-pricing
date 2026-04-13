from app.services.stock_client import get_recent_history_from_stock_service


def get_product_kpis_service(product_id: int, days: int, db) -> dict:
    rows = get_recent_history_from_stock_service(product_id=str(product_id), limit=days)

    if not rows:
        return {
            "product_id": product_id,
            "period_days": days,
            "quantity_sold": 0.0,
            "sales_velocity_per_day": 0.0,
            "stock_rotation": 0.0,
            "average_stock": 0.0,
            "estimated_start_stock": 0.0,
            "history": [],
        }

    quantity_sold = sum(float(r.get("sales") or 0.0) for r in rows)

    stock_values = [float(r.get("stock") or 0.0) for r in rows]
    average_stock = sum(stock_values) / len(stock_values) if stock_values else 0.0

    last_stock = float(rows[-1].get("stock") or 0.0)
    estimated_start_stock = last_stock + quantity_sold

    sales_velocity_per_day = quantity_sold / days if days > 0 else 0.0
    stock_rotation = quantity_sold / average_stock if average_stock > 0 else 0.0

    return {
        "product_id": product_id,
        "period_days": days,
        "quantity_sold": round(quantity_sold, 2),
        "sales_velocity_per_day": round(sales_velocity_per_day, 4),
        "stock_rotation": round(stock_rotation, 4),
        "average_stock": round(average_stock, 2),
        "estimated_start_stock": round(estimated_start_stock, 2),
        "history": rows,
    }