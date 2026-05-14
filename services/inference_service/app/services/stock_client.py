from __future__ import annotations

import os
from typing import Any
import requests


STOCK_SERVICE_URL = os.getenv("STOCK_SERVICE_URL", "http://stock_service:2004")
STOCK_SERVICE_PUBLIC_URL = os.getenv("STOCK_SERVICE_PUBLIC_URL", "http://localhost:2004")


def _base_url() -> str:
    return STOCK_SERVICE_URL.rstrip("/")


def _public_base_url() -> str:
    return STOCK_SERVICE_PUBLIC_URL.rstrip("/")


def _get_json(path: str, params: dict | None = None, timeout: int = 30):
    """
    Essaie d'abord l'URL Docker interne, puis localhost en fallback.
    """
    urls = [
        f"{_base_url()}{path}",
        f"{_public_base_url()}{path}",
    ]

    last_error = None
    for url in urls:
        try:
            response = requests.get(url, params=params, timeout=timeout)
            if response.status_code == 404:
                last_error = RuntimeError(f"404 {url}")
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc

    raise last_error or RuntimeError(f"Impossible d'appeler {path}")


def get_product_by_id(product_id: Any) -> dict | None:
    candidates = [
        f"/products/{product_id}",
        f"/api/v1/products/{product_id}",
    ]

    for path in candidates:
        try:
            data = _get_json(path, timeout=20)
            if isinstance(data, dict):
                return data
        except Exception:
            continue

    return None


def get_recent_history_from_stock_service(
    product_id: Any,
    limit: int = 140,
) -> list[dict]:
    """
    Récupère l'historique de ventes depuis stock_service.

    Important :
    - limit >= 120 pour lag_90 et rolling_90.
    - product_id doit idéalement être le SKU, pas l'id numérique.
    """
    params = {"product_id": str(product_id), "limit": int(limit)}

    candidates = [
        "/sales-history/recent",
        "/api/v1/sales-history/recent",
    ]

    for path in candidates:
        try:
            data = _get_json(path, params=params, timeout=60)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ["items", "data", "results", "history"]:
                    if isinstance(data.get(key), list):
                        return data[key]
        except Exception:
            continue

    return []


# Alias compatibles avec plusieurs anciens codes
get_recent_sales_history = get_recent_history_from_stock_service
get_product_history = get_recent_history_from_stock_service


def get_product_from_stock_service(product_id: Any) -> dict:
    """
    Alias utilisé par recommend_price.py.
    """
    product = get_product_by_id(product_id)

    if product is None:
        raise RuntimeError(f"Produit introuvable dans stock_service: {product_id}")

    return product


def get_sales_history_from_stock_service(
    store_id: str | None = None,
    product_id: Any | None = None,
    target_date: str | None = None,
    n_days: int = 90,
    limit: int | None = None,
) -> list[dict]:
    """
    Alias de compatibilité pour les anciens modules ML.
    La logique reste basée sur get_recent_history_from_stock_service().
    """
    return get_recent_history_from_stock_service(
        product_id=product_id,
        limit=int(limit or n_days or 90),
    )
def get_elimination_recommendation_from_stock_service(product_id, *args, **kwargs):
    """
    Compatibilité avec promo_service.py.
    Récupère une recommandation d'élimination depuis stock_service si elle existe.
    Sinon retourne une valeur neutre sans casser inference_service.
    """
    try:
        url = f"{STOCK_SERVICE_URL}/products/{product_id}/elimination-recommendation"
        response = requests.get(url, timeout=30)

        if response.status_code == 200:
            return response.json()

        return {
            "product_id": product_id,
            "should_eliminate": False,
            "recommendation": None,
            "status": "not_available",
        }

    except Exception:
        return {
            "product_id": product_id,
            "should_eliminate": False,
            "recommendation": None,
            "status": "fallback",
        }