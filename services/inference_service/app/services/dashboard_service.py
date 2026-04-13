import os
import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.request_builder import build_request_from_product
from app.services.demand_service import forecast_demand_service
from app.services.restock_service import recommend_restock_service
from app.services.price_service import recommend_price_service

STOCK_SERVICE_URL = os.getenv("STOCK_SERVICE_URL", "http://localhost:8004")


def dashboard_recommendations_service(db: Session) -> dict:
    try:
        response = requests.get(f"{STOCK_SERVICE_URL}/products", timeout=10)
        response.raise_for_status()
        products = response.json()
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="stock_service timeout")
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Erreur stock_service: {str(e)}")

    if not isinstance(products, list):
        return {
            "summary": {
                "total_products": 0,
                "critical_restock_count": 0,
                "price_change_count": 0,
                "promo_count": 0,
            },
            "recommendations": []
        }

    recommendations = []

    for product in products[:20]:
        try:
            req = build_request_from_product(product)
            demand = forecast_demand_service(req, db)
            restock = recommend_restock_service(req, db)
            price = recommend_price_service(req, db)

            current_price = float(product.get("current_price", 0.0))
            price_changed = abs(price.recommended_price - current_price) > 0.01

            recommendations.append({
                "product_id": product.get("product_id"),
                "name": product.get("name"),
                "sku": product.get("sku"),
                "category": product.get("category"),
                "current_stock": product.get("current_stock"),
                "current_price": current_price,
                "forecast_weekly_demand": round(demand.predicted_demand, 2),
                "restock_needed": restock.restock_needed,
                "recommended_restock_qty": restock.recommended_order_qty,
                "restock_urgency": restock.urgency,
                "recommended_price": round(price.recommended_price, 2),
                "price_change_pct": price.price_change_pct,
                "price_change_needed": price_changed,
            })
        except Exception:
            continue

    critical_restock_count = sum(
        1 for r in recommendations if r["restock_urgency"] in ["high", "critical"]
    )
    price_change_count = sum(1 for r in recommendations if r["price_change_needed"])
    promo_count = sum(
        1 for r in recommendations
        if (r["current_stock"] or 0) > 0
        and (r["recommended_restock_qty"] or 0) == 0
        and (r["price_change_pct"] or 0) < 0
    )

    return {
        "summary": {
            "total_products": len(recommendations),
            "critical_restock_count": critical_restock_count,
            "price_change_count": price_change_count,
            "promo_count": promo_count,
        },
        "recommendations": recommendations,
    }