from typing import Dict

import httpx
from fastapi import APIRouter, Request, Response

from app.core.config import settings

router = APIRouter(tags=["gateway-proxy"])

SERVICE_MAP: Dict[str, str] = {
    "auth-service": settings.AUTH_SERVICE_URL,
    "stock-service": settings.STOCK_SERVICE_URL,
    "ml-service": settings.ML_SERVICE_URL,
    "scraping-service": settings.SCRAPING_SERVICE_URL,
    "csv-service": settings.CSV_IMPORT_SERVICE_URL,
    "alerts-service": settings.ALERTS_SERVICE_URL,
}

LONG_TIMEOUT_SERVICES = {"scraping-service", "csv-service", "ml-service"}

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _clean_request_headers(request: Request) -> dict:
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _clean_response_headers(response: httpx.Response) -> dict:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


async def _proxy(service_key: str, path: str, request: Request) -> Response:
    base_url = SERVICE_MAP[service_key].rstrip("/")
    target_url = f"{base_url}/{path.lstrip('/')}" if path else base_url

    body = await request.body()

    timeout = (
        settings.LONG_TIMEOUT_SECONDS
        if service_key in LONG_TIMEOUT_SERVICES
        else settings.DEFAULT_TIMEOUT_SECONDS
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            upstream_response = await client.request(
                method=request.method,
                url=target_url,
                params=request.query_params,
                headers=_clean_request_headers(request),
                content=body,
            )
        except httpx.ConnectError:
            return Response(
                content=f"Service indisponible: {service_key} ({base_url})",
                status_code=503,
                media_type="text/plain",
            )
        except httpx.TimeoutException:
            return Response(
                content=f"Timeout gateway vers {service_key}",
                status_code=504,
                media_type="text/plain",
            )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=_clean_response_headers(upstream_response),
        media_type=upstream_response.headers.get("content-type"),
    )


@router.api_route(
    "/{service_key}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_service_root(service_key: str, request: Request):
    if service_key not in SERVICE_MAP:
        return Response(content="Service inconnu", status_code=404)

    return await _proxy(service_key, "", request)


@router.api_route(
    "/{service_key}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_service_path(service_key: str, path: str, request: Request):
    if service_key not in SERVICE_MAP:
        return Response(content="Service inconnu", status_code=404)

    return await _proxy(service_key, path, request)