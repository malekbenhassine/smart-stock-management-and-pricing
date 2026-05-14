from dataclasses import dataclass
from typing import Any, Optional
import os
from datetime import date
from app.schemas import BaseRequest


DEFAULT_STORE_ID = os.getenv("DEFAULT_STORE_ID", "S001")
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "Tunis")
DEFAULT_WEATHER = os.getenv("DEFAULT_WEATHER", "Sunny")
DEFAULT_SEASONALITY = os.getenv("DEFAULT_SEASONALITY", "Regular")


@dataclass
class DemandRequest:
    product_id: Any
    sku: Optional[str] = None
    name: Optional[str] = None
    category: str = "Accessories"
    brand: Optional[str] = None
    price: float = 0.0
    stock: float = 0.0
    discount: float = 0.0
    competitor_pricing: float = 0.0
    units_ordered: float = 0.0
    store_id: str = DEFAULT_STORE_ID
    region: str = DEFAULT_REGION
    weather_condition: str = DEFAULT_WEATHER
    holiday_promotion: int = 0
    seasonality: str = DEFAULT_SEASONALITY


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _pick(obj: Any, *names: str, default=None):
    if obj is None:
        return default

    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default

    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value

    return default


def normalize_category(raw: Any) -> str:
    value = str(raw or "").lower()

    if any(k in value for k in ["pc portable", "laptop", "notebook", "expertbook", "vivobook"]):
        return "Laptops"
    if any(k in value for k in ["souris", "clavier", "accessoire", "mouse", "keyboard", "casque"]):
        return "Accessories"
    if any(k in value for k in ["routeur", "wifi", "switch", "network"]):
        return "Network"
    if any(k in value for k in ["imprimante", "printer"]):
        return "Printers"
    if any(k in value for k in ["ecran", "écran", "monitor"]):
        return "Monitors"
    if any(k in value for k in ["desktop", "bureau"]):
        return "Desktops"
    if any(k in value for k in ["ram", "ssd", "disque", "component"]):
        return "Components"
    if any(k in value for k in ["montre", "watch", "audio", "wearable"]):
        return "WearablesAudio"

    return "Accessories"


def build_demand_request(product: Any, context: dict | None = None) -> DemandRequest:
    """
    Construit une requête propre pour le modèle depuis un produit stock_service.

    Compatible dict ou objet ORM/Pydantic.
    """
    context = context or {}

    sku = _pick(product, "sku", "reference", "code", default=None)
    product_id = _pick(product, "id", "product_id", default=sku)

    price = _safe_float(
        _pick(product, "prix_vente", "prixVente", "prixVenteTTC", "price", "current_price", default=0)
    )
    stock = _safe_float(
        _pick(product, "stock_disponible", "stockDisponible", "stock", "current_stock", "quantite", default=0)
    )

    competitor_pricing = _safe_float(
        context.get("competitor_pricing"),
        default=price
    )

    return DemandRequest(
        product_id=product_id,
        sku=str(sku) if sku else None,
        name=_pick(product, "nom", "name", default=None),
        category=normalize_category(_pick(product, "categorie", "category", default="Accessories")),
        brand=_pick(product, "marque", "brand", default=None),
        price=price,
        stock=stock,
        discount=_safe_float(context.get("discount"), 0.0),
        competitor_pricing=competitor_pricing if competitor_pricing > 0 else price,
        units_ordered=_safe_float(context.get("units_ordered"), 0.0),
        store_id=str(context.get("store_id") or DEFAULT_STORE_ID),
        region=str(context.get("region") or DEFAULT_REGION),
        weather_condition=str(context.get("weather_condition") or DEFAULT_WEATHER),
        holiday_promotion=int(_safe_float(context.get("holiday_promotion"), 0)),
        seasonality=str(context.get("seasonality") or DEFAULT_SEASONALITY),
    )
def build_request_from_product(product: dict) -> BaseRequest:
    """
    Construit un BaseRequest complet à partir d'un produit stock_service.
    Correction de compatibilité : les services price/restock/stock_risk attendent
    des attributs Pydantic (req.price, req.stock, req.date...), pas un dict.
    """
    if product is None:
        raise ValueError("Produit introuvable")

    product_id = _pick(product, "sku", "reference", "code", "id", "product_id", default=None)
    if product_id is None:
        raise ValueError("Produit sans identifiant exploitable")

    price = _safe_float(
        _pick(product, "prixVente", "prix_vente", "prixVenteTTC", "current_price", "price", default=0.0),
        0.0,
    )
    if price <= 0:
        price = 1.0

    stock = _safe_float(
        _pick(product, "stockDisponible", "stock_disponible", "quantiteStock", "quantite", "current_stock", "stock", default=0.0),
        0.0,
    )

    threshold_min = _safe_float(
        _pick(product, "seuilMin", "threshold_min", "stockMin", "min_stock", default=0.0),
        0.0,
    )
    threshold_max = _safe_float(
        _pick(product, "seuilMax", "threshold_max", "stockMax", "max_stock", default=0.0),
        0.0,
    )

    cost_price = _safe_float(
        _pick(product, "prixCout", "prix_cout", "cost_price", "cout", default=0.0),
        0.0,
    )
    min_margin = _safe_float(
        _pick(product, "min_margin", "margeReservee", "marge_min", default=0.0),
        0.0,
    )

    category = normalize_category(_pick(product, "categorie", "category", default="Accessories"))
    brand = _pick(product, "marque", "brand", default=None)

    return BaseRequest(
        store_id=str(_pick(product, "store_id", "magasin", default=DEFAULT_STORE_ID) or DEFAULT_STORE_ID),
        product_id=str(product_id),
        date=date.today(),
        price=float(price),
        stock=float(max(stock, 0.0)),
        discount=_safe_float(_pick(product, "discount", "remise", default=0.0), 0.0),
        competitor_pricing=_safe_float(_pick(product, "competitor_pricing", "prixConcurrent", default=price), price),
        units_ordered=_safe_float(_pick(product, "units_ordered", "quantiteCommandee", default=0.0), 0.0),
        weather_condition=str(_pick(product, "weather_condition", default=DEFAULT_WEATHER) or DEFAULT_WEATHER),
        category=category,
        region=str(_pick(product, "region", default=DEFAULT_REGION) or DEFAULT_REGION),
        threshold_min=threshold_min,
        threshold_max=threshold_max,
        cost_price=cost_price,
        min_price=cost_price if cost_price > 0 else None,
        brand=brand,
        min_margin=min_margin,
        peak_season=_pick(product, "peak_season", "season", default=None),
        seasonality_factor=_safe_float(_pick(product, "seasonality_factor", default=1.0), 1.0),
    )
