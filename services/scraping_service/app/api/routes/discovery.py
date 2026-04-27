from fastapi import APIRouter, HTTPException

from app.schemas.scraping_schemas import DiscoverSiteRequest
from app.services.discovery_service import DiscoveryService

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/site")
def discover_site(payload: DiscoverSiteRequest):
    service = DiscoveryService()
    try:
        return service.discover_site(payload.site_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur découverte: {str(exc)}")