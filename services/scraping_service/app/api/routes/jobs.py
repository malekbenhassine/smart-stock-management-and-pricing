from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.scraping_schemas import RunNowRequest
from app.services.scraping_service import ScrapingService


router = APIRouter(prefix="/jobs", tags=["jobs"])


class ProductSearchRequest(BaseModel):
    product_id: int
    sku: Optional[str] = None
    nom: str
    marque: Optional[str] = None
    description: Optional[str] = None
    categorie: Optional[str] = None


@router.post("/run-now")
def run_now(payload: RunNowRequest):
    scraper = ScrapingService()

    try:
        return scraper.scrape_due_or_all(competitor_id=payload.competitor_id)

    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur scraping: {str(exc)}")


@router.post("/search-product")
def search_product_on_competitors(
    payload: ProductSearchRequest,
    debug: bool = False,
):
    scraper = ScrapingService()

    try:
        result = scraper.search_product_on_all_competitors(
            payload.model_dump(),
            debug=debug,
        )
        return result

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur recherche ciblée produit: {str(exc)}",
        )