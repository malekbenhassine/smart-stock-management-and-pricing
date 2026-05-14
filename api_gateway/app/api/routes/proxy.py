from typing import Dict

import httpx
from fastapi import APIRouter, Request, Response

from app.core.config import settings

router = APIRouter(tags=["gateway-proxy"])

# On garde les anciens noms utilisés par le front + des alias plus courts.
SERVICE_MAP: Dict[str, str] = {
    "auth-service": settings.AUTH_SERVICE_URL,
    "auth": settings.AUTH_SERVICE_URL,
    "stock-service": settings.STOCK_SERVICE_URL,
    "stock": settings.STOCK_SERVICE_URL,
    "ml-service": settings.ML_SERVICE_URL,
    "ml": settings.ML_SERVICE_URL,
    "scraping-service": settings.SCRAPING_SERVICE_URL,
    "scraping": settings.SCRAPING_SERVICE_URL,
    "csv-service": settings.CSV_IMPORT_SERVICE_URL,
    "csv": settings.CSV_IMPORT_SERVICE_URL,
    "alerts-service": settings.ALERTS_SERVICE_URL,
    "alerts": settings.ALERTS_SERVICE_URL,
}

LONG_TIMEOUT_SERVICES = {
    "scraping-service",
    "scraping",
    "csv-service",
    "csv",
    "ml-service",
    "ml",
    "stock-service",
    "stock",
}

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


def _json_error(message: str, status_code: int) -> Response:
    return Response(
        content=f'{{"detail":"{message}"}}',
        status_code=status_code,
        media_type="application/json",
    )


async def _proxy(service_key: str, path: str, request: Request) -> Response:
    if service_key not in SERVICE_MAP:
        return _json_error("Service inconnu", 404)

    full_url = str(request.url)
    if len(full_url) > settings.MAX_URL_LENGTH:
        return _json_error(
            "URL trop longue. Utilise une route POST avec un body JSON au lieu de mettre les données dans l'URL.",
            414,
        )

    # Réponse rapide aux pré-requêtes CORS.
    if request.method == "OPTIONS":
        return Response(status_code=204)

    base_url = SERVICE_MAP[service_key].rstrip("/")
    target_url = f"{base_url}/{path.lstrip('/')}" if path else base_url

    body = await request.body()
    timeout = (
        settings.LONG_TIMEOUT_SECONDS
        if service_key in LONG_TIMEOUT_SERVICES
        else settings.DEFAULT_TIMEOUT_SECONDS
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            upstream_response = await client.request(
                method=request.method,
                url=target_url,
                params=request.query_params,
                headers=_clean_request_headers(request),
                content=body,
            )
        except httpx.ConnectError:
            return _json_error(f"Service indisponible: {service_key} ({base_url})", 503)
        except httpx.TimeoutException:
            return _json_error(f"Timeout gateway vers {service_key}", 504)
        except httpx.HTTPError as exc:
            return _json_error(f"Erreur gateway vers {service_key}: {str(exc)}", 502)

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
    return await _proxy(service_key, "", request)


@router.api_route(
    "/{service_key}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_service_path(service_key: str, path: str, request: Request):
    return await _proxy(service_key, path, request)
