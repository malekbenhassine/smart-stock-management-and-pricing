from datetime import date
import os

from app.schemas import BaseRequest

DEFAULT_STORE_ID = os.getenv("DEFAULT_STORE_ID", "STORE_Nord")
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "UNKNOWN")


def build_request_from_product(product: dict) -> BaseRequest:
    current_price = float(product.get("current_price", product.get("prixVente", 0.0)))
    current_stock = float(product.get("current_stock", product.get("stockDisponible", 0.0)))
    cost_price = product.get("cost_price", product.get("prixCout"))
    min_price = product.get("min_price")
    threshold_min = product.get("threshold_min", product.get("seuilMin", 0.0))
    threshold_max = product.get("threshold_max", product.get("seuilMax", 0.0))
    discount = float(product.get("discount", 0.0) or 0.0)

    # IMPORTANT : l’IA travaille avec le SKU
    model_product_id = str(
        product.get("sku")
        or product.get("product_id")
        or product.get("id")
    )

    return BaseRequest(
        store_id=str(product.get("store_id", DEFAULT_STORE_ID)),
        product_id=model_product_id,
        date=date.today(),
        price=current_price,
        stock=current_stock,
        discount=discount,
        competitor_pricing=product.get("competitor_pricing"),
        units_ordered=float(product.get("units_ordered", 0.0) or 0.0),
        weather_condition=product.get("weather_condition"),
        category=product.get("category", product.get("categorie")),
        region=product.get("region", DEFAULT_REGION),
        threshold_min=float(threshold_min or 0.0),
        threshold_max=float(threshold_max or 0.0),
        cost_price=float(cost_price) if cost_price is not None else None,
        min_price=float(min_price) if min_price is not None else None,
        brand=product.get("brand", product.get("marque")),
    )