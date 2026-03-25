from pathlib import Path
import csv
import requests
from fastapi import HTTPException

DATA_FILE = Path(__file__).resolve().parents[4] / "data" / "products.csv"
ML_SERVICE_URL = "http://localhost:8020"


def parse_bool(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_product(row):
    return {
        "product_id": int(row["product_id"]),
        "sku": row["sku"],
        "name": row["name"],
        "category": row["category"],
        "brand": row["brand"],
        "unit": row["unit"],
        "cost_price": float(row["cost_price"]),
        "min_margin": float(row["min_margin"]),
        "min_price": float(row["min_price"]),
        "current_price": float(row["current_price"]),
        "threshold_min": int(row["threshold_min"]),
        "threshold_max": int(row["threshold_max"]),
        "current_stock": int(row["current_stock"]),
        "created_at": row["created_at"],
        "is_active": parse_bool(row["is_active"]),
    }


def load_products():
    if not DATA_FILE.exists():
        raise HTTPException(status_code=500, detail="products.csv introuvable")

    with open(DATA_FILE, mode="r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [parse_product(row) for row in reader]


def get_product_or_404(product_id: int):
    products = load_products()
    product = next((p for p in products if p["product_id"] == product_id), None)

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    return product


def call_ml_service(endpoint: str):
    try:
        response = requests.get(f"{ML_SERVICE_URL}{endpoint}", timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        return {
            "error": True,
            "endpoint": endpoint,
            "message": "Timeout du service ML"
        }
    except requests.RequestException as e:
        return {
            "error": True,
            "endpoint": endpoint,
            "message": str(e)
        }


def get_all_products(q: str | None = None, limit: int = 100):
    products = load_products()

    if q:
        search = q.strip().lower()
        products = [
            p for p in products
            if search in p["name"].lower()
            or search in p["sku"].lower()
            or search in p["brand"].lower()
            or search in p["category"].lower()
        ]

    return {
        "items": products[:limit],
        "total": len(products),
    }


def get_product_by_id_service(product_id: int):
    return get_product_or_404(product_id)


def get_product_pricing_details_service(product_id: int):
    product = get_product_or_404(product_id)

    return {
        "product": product,
        "price_recommendation": call_ml_service(f"/recommend/price/{product_id}"),
        "promo_recommendation": call_ml_service(f"/recommend/promo/{product_id}"),
    }


def get_product_stock_details_service(product_id: int):
    product = get_product_or_404(product_id)

    return {
        "product": product,
        "demand_prediction": call_ml_service(f"/predict/demand-weekly/{product_id}"),
        "stock_risk": call_ml_service(f"/predict/stock-risk/{product_id}"),
        "restock_recommendation": call_ml_service(f"/recommend/restock/{product_id}"),
        "anomalies": call_ml_service(f"/detect/anomalies/{product_id}"),
    }