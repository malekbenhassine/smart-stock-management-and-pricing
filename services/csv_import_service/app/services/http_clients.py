import os
import httpx
from fastapi import HTTPException

STOCK_SERVICE_URL = os.getenv("STOCK_SERVICE_URL", "http://stock_service:2004")
INFERENCE_SERVICE_URL = os.getenv("INFERENCE_SERVICE_URL", "http://inference_service:8020")

STOCK_TIMEOUT = int(os.getenv("STOCK_TIMEOUT", "120"))
INFERENCE_TIMEOUT = int(os.getenv("INFERENCE_TIMEOUT", "120"))

# Clients réutilisables (évite de recréer une connexion TCP à chaque appel)
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
        raise HTTPException(
            status_code=response.status_code,
            detail=f"{response.status_code}: {response.text}",
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
