import os
import requests
from fastapi import HTTPException

STOCK_SERVICE_URL = os.getenv("STOCK_SERVICE_URL", "http://stock_service:2004")


def get_product_from_stock_service(product_id: int) -> dict:
    try:
        response = requests.get(
            f"{STOCK_SERVICE_URL}/products/{product_id}",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="stock_service timeout")
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Erreur stock_service: {str(e)}")


def get_sales_history_from_stock_service(
    store_id: str,
    product_id: str,
    target_date: str,
    n_days: int = 90,
) -> list[dict]:
    try:
        response = requests.get(
            f"{STOCK_SERVICE_URL}/sales-history",
            params={
                "store_id": store_id,
                "product_id": product_id,
                "target_date": target_date,
                "n_days": n_days,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="stock_service history timeout")
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur stock_service history: {str(e)}",
        )


def get_recent_history_from_stock_service(product_id: str, limit: int = 30) -> list[dict]:
    try:
        response = requests.get(
            f"{STOCK_SERVICE_URL}/sales-history/recent",
            params={
                "product_id": product_id,
                "limit": limit,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="stock_service recent history timeout")
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur stock_service recent history: {str(e)}",
        )


def get_latest_sales_date_from_stock_service(product_id: str) -> str | None:
    """
    Récupère automatiquement la dernière date de vente disponible pour le produit.

    Important :
    - on ne met pas de date fixe ;
    - si tu ajoutes de nouvelles ventes, la dernière date changera automatiquement ;
    - on utilise la route déjà existante /sales-history/recent.
    """
    try:
        rows = get_recent_history_from_stock_service(product_id=product_id, limit=365)

        if not rows:
            return None

        dates = [
            row.get("date")
            for row in rows
            if row.get("date")
        ]

        if not dates:
            return None

        return max(dates)

    except Exception:
        return None