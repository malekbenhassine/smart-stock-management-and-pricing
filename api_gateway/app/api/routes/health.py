import httpx
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["gateway-health"])

SERVICES = {
    "auth": settings.AUTH_SERVICE_URL,
    "stock": settings.STOCK_SERVICE_URL,
    "ml": settings.ML_SERVICE_URL,
    "scraping": settings.SCRAPING_SERVICE_URL,
    "csv_import": settings.CSV_IMPORT_SERVICE_URL,
}


@router.get("/health")
async def gateway_health():
    return {"status": "ok", "service": settings.APP_NAME}


@router.get("/health/services")
async def services_health():
    results = {}

    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, base_url in SERVICES.items():
            try:
                response = await client.get(f"{base_url}/health")
                results[name] = {
                    "ok": response.status_code < 500,
                    "status_code": response.status_code,
                    "url": base_url,
                }
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "error": str(exc),
                    "url": base_url,
                }

    return {"gateway": "ok", "services": results}


@router.get("/routes")
def gateway_routes():
    return {
        "auth": "/auth-service/... -> auth_service:8007/...",
        "stock": "/stock-service/... -> stock_service:2004/...",
        "ml": "/ml-service/... -> inference_service:8020/...",
        "scraping": "/scraping-service/... -> scraping_service:8060/...",
        "csv_import": "/csv-service/... -> csv_import_service:8030/...",
        "alerts_optional": "/alerts-service/... -> alerts_service:8006/...",
    }