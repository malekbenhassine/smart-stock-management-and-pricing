from datetime import date
import os

from app.schemas import BaseRequest

DEFAULT_STORE_ID = os.getenv("DEFAULT_STORE_ID", "STORE_Nord")
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "UNKNOWN")

def infer_peak_season_from_category(category: str | None) -> str | None:
    if not category:
        return None

    cat = category.strip().lower()

    mapping = {
        "laptops": "Autumn",
        "desktops": "Autumn",
        "gpu": "Autumn",
        "cpu": "Autumn",
        "mémoire ram": "Autumn",
        "moniteurs": "Autumn",
        "périphériques": "AllSeason",
        "réseaux": "AllSeason",
        "stockage": "AllSeason",
        "câbles & accessoires": "AllSeason",
        "claviers & souris": "AllSeason",
    }

    return mapping.get(cat)


def compute_seasonality_factor(peak_season: str | None, current_date: date) -> float:
    month = current_date.month

    current_season = {
        12: "Winter", 1: "Winter", 2: "Winter",
        3: "Spring", 4: "Spring", 5: "Spring",
        6: "Summer", 7: "Summer", 8: "Summer",
        9: "Autumn", 10: "Autumn", 11: "Autumn",
    }[month]

    if not peak_season:
        return 1.0

    if peak_season == current_season:
        return 1.10

    return 0.92

def build_request_from_product(product: dict) -> BaseRequest:
    current_price = float(product.get("current_price", product.get("prixVente", 0.0)))
    current_stock = float(product.get("current_stock", product.get("stockDisponible", 0.0)))
    cost_price = product.get("cost_price", product.get("prixCout"))
    min_price = product.get("min_price")
    threshold_min = product.get("threshold_min", product.get("seuilMin", 0.0))
    threshold_max = product.get("threshold_max", product.get("seuilMax", 0.0))
    discount = float(product.get("discount", 0.0) or 0.0)
    min_margin = product.get("min_margin", product.get("margeReservee"))
    model_product_id = str(
        product.get("sku")
        or product.get("product_id")
        or product.get("id")
    )

    category = product.get("category", product.get("categorie"))
    target_date = date.today()

    peak_season = (
        product.get("peak_season")
        or product.get("season")
        or infer_peak_season_from_category(category)
    )

    seasonality_factor = compute_seasonality_factor(peak_season, target_date)

    return BaseRequest(
        store_id=str(product.get("store_id", DEFAULT_STORE_ID)),
        product_id=model_product_id,
        date=target_date,
        price=current_price,
        stock=current_stock,
        discount=discount,
        competitor_pricing=product.get("competitor_pricing"),
        units_ordered=float(product.get("units_ordered", 0.0) or 0.0),
        weather_condition=product.get("weather_condition"),
        category=category,
        region=product.get("region", DEFAULT_REGION),
        threshold_min=float(threshold_min or 0.0),
        threshold_max=float(threshold_max or 0.0),
        cost_price=float(cost_price) if cost_price is not None else None,
        min_price=float(min_price) if min_price is not None else None,
        min_margin=float(min_margin) / 100 if min_margin is not None else 0.0,
        brand=product.get("brand", product.get("marque")),
        peak_season=peak_season,
        seasonality_factor=seasonality_factor,
    )