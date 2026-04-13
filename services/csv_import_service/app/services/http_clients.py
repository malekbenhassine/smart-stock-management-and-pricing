import os
import requests
from fastapi import HTTPException

STOCK_SERVICE_URL = os.getenv("STOCK_SERVICE_URL", "http://stock_service:2004")
INFERENCE_SERVICE_URL = os.getenv("INFERENCE_SERVICE_URL", "http://inference_service:8020")

STOCK_TIMEOUT = int(os.getenv("STOCK_TIMEOUT", "120"))
INFERENCE_TIMEOUT = int(os.getenv("INFERENCE_TIMEOUT", "120"))


def post_to_stock(endpoint: str, payload: list[dict]):
    response = requests.post(
        f"{STOCK_SERVICE_URL}{endpoint}",
        json=payload,
        timeout=STOCK_TIMEOUT,
    )
    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"{response.status_code}: {response.text}"
        )
    return response.json()


def post_to_inference(endpoint: str, payload: list[dict]):
    response = requests.post(
        f"{INFERENCE_SERVICE_URL}{endpoint}",
        json=payload,
        timeout=INFERENCE_TIMEOUT,
    )
    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"{response.status_code}: {response.text}"
        )
    return response.json()