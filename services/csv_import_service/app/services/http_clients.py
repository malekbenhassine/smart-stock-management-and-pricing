import os

import httpx
from fastapi import HTTPException

STOCK_SERVICE_URL = os.getenv("STOCK_SERVICE_URL", "http://stock_service:2004")
INFERENCE_SERVICE_URL = os.getenv("INFERENCE_SERVICE_URL", "http://inference_service:8020")

STOCK_TIMEOUT = int(os.getenv("STOCK_TIMEOUT", "120"))
INFERENCE_TIMEOUT = int(os.getenv("INFERENCE_TIMEOUT", "120"))

_stock_client: httpx.AsyncClient | None = None
_inference_client: httpx.AsyncClient | None = None


def get_stock_client() -> httpx.AsyncClient:
    global _stock_client

    if _stock_client is None or _stock_client.is_closed:
        _stock_client = httpx.AsyncClient(
            base_url=STOCK_SERVICE_URL,
            timeout=STOCK_TIMEOUT,
        )

    return _stock_client


def get_inference_client() -> httpx.AsyncClient:
    global _inference_client

    if _inference_client is None or _inference_client.is_closed:
        _inference_client = httpx.AsyncClient(
            base_url=INFERENCE_SERVICE_URL,
            timeout=INFERENCE_TIMEOUT,
        )

    return _inference_client


async def post_to_stock(endpoint: str, payload: list[dict]):
    client = get_stock_client()

    response = await client.post(endpoint, json=payload)

    if not response.is_success:
        body = response.text
        try:
            body = response.json()
        except Exception:
            pass

        sample = payload[:2] if isinstance(payload, list) else payload

        raise HTTPException(
            status_code=response.status_code,
            detail={
                "target": "stock_service",
                "endpoint": endpoint,
                "status_code": response.status_code,
                "response": body,
                "rows_sent": len(payload) if isinstance(payload, list) else None,
                "sample_rows": sample,
            },
        )

    return response.json()


async def post_to_inference(endpoint: str, payload: list[dict]):
    client = get_inference_client()

    response = await client.post(endpoint, json=payload)

    if not response.is_success:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"{response.status_code}: {response.text}",
        )

    return response.json()


async def trigger_post_import_workflow(
    table_name: str,
    max_products: int = 30,
    product_ids: list[int] | None = None,
):
    client = get_stock_client()

    try:
        response = await client.post(
            "/imports/after-import",
            json={
                "table_name": table_name,
                "max_products": max_products,
                "async_mode": True,
                "product_ids": product_ids or [],
            },
            timeout=30,
        )

        if not response.is_success:
            return {
                "status": "error",
                "detail": f"{response.status_code}: {response.text}",
            }

        return response.json()

    except Exception as exc:
        return {
            "status": "error",
            "detail": str(exc),
        }
        
async def notify_stock_import_activity(payload: dict):
    client = get_stock_client()

    try:
        response = await client.post(
            "/manager/journal-activites/import-csv",
            json=payload,
            timeout=30,
        )

        if not response.is_success:
            return {
                "status": "error",
                "detail": f"{response.status_code}: {response.text}",
            }

        return response.json()

    except Exception as exc:
        return {
            "status": "error",
            "detail": str(exc),
        }