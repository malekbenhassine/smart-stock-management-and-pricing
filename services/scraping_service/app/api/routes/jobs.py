from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas.scraping_schemas import (
    RunNowRequest,
    ProductScheduleCreate,
    ProductRunNowRequest,
    CatalogFrequencyConfig,
)
from app.services.scheduler_service import dual_scheduler


router = APIRouter(prefix="/jobs", tags=["jobs"])


class ProductSearchRequest(BaseModel):
    product_id: int
    sku: Optional[str] = None
    nom: str
    marque: Optional[str] = None
    description: Optional[str] = None
    categorie: Optional[str] = None
    launched_by_user_id: Optional[int] = None
    user_id: Optional[int] = None


def resolve_user_id(payload_user_id=None, payload_launched_by_user_id=None, query_user_id=None):
    return payload_launched_by_user_id or payload_user_id or query_user_id


@router.post("/run-now")
def run_now(payload: RunNowRequest, user_id: Optional[int] = Query(default=None)):
    launched_by_user_id = resolve_user_id(
        payload_launched_by_user_id=payload.launched_by_user_id,
        query_user_id=user_id,
    )

    return {
        "status": "started",
        "message": "Scraping catalogue lancé en arrière-plan.",
        "job": dual_scheduler.run_catalog_now(
            competitor_id=payload.competitor_id,
            launched_by_user_id=launched_by_user_id,
        ),
    }


@router.post("/search-product")
def search_product_on_competitors(
    payload: ProductSearchRequest,
    debug: bool = False,
    fast: bool = True,
    user_id: Optional[int] = Query(default=None),
):
    try:
        launched_by_user_id = resolve_user_id(
            payload_user_id=payload.user_id,
            payload_launched_by_user_id=payload.launched_by_user_id,
            query_user_id=user_id,
        )

        print("[SCRAPING_ROUTE] /search-product launched_by_user_id =", launched_by_user_id, flush=True)

        job = dual_scheduler.run_product_job_now(
            product_ids=[payload.product_id],
            fast=fast,
            debug=debug,
            launched_by_user_id=launched_by_user_id,
        )

        return {
            "status": "started",
            "message": "Recherche produit lancée en arrière-plan.",
            "job_id": job.get("id"),
            "job": job,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/product-schedules")
def create_product_schedule(payload: ProductScheduleCreate, user_id: Optional[int] = Query(default=None)):
    try:
        launched_by_user_id = resolve_user_id(
            payload_launched_by_user_id=payload.launched_by_user_id,
            query_user_id=user_id,
        )

        return dual_scheduler.create_product_job(
            product_ids=payload.product_ids,
            run_at=payload.run_at,
            fast=payload.fast,
            debug=payload.debug,
            title=payload.title,
            launched_by_user_id=launched_by_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/product-schedules")
def list_product_schedules():
    return {
        "status": "success",
        "jobs": dual_scheduler.list_product_jobs(),
    }


@router.get("/product-schedules/{job_id}")
def get_product_schedule(job_id: str):
    job = dual_scheduler.get_product_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable.")

    return job


@router.delete("/product-schedules/{job_id}")
def cancel_product_schedule(job_id: str):
    try:
        return dual_scheduler.cancel_product_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/product-run-now")
def product_run_now(payload: ProductRunNowRequest, user_id: Optional[int] = Query(default=None)):
    try:
        launched_by_user_id = resolve_user_id(
            payload_launched_by_user_id=payload.launched_by_user_id,
            query_user_id=user_id,
        )

        print("[SCRAPING_ROUTE] /product-run-now launched_by_user_id =", launched_by_user_id, flush=True)

        return dual_scheduler.run_product_job_now(
            product_ids=payload.product_ids,
            fast=payload.fast,
            debug=payload.debug,
            launched_by_user_id=launched_by_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/catalog-frequency")
def configure_catalog_frequency(payload: CatalogFrequencyConfig):
    return dual_scheduler.configure_catalog_frequency(
        enabled=payload.enabled,
        interval_minutes=payload.interval_minutes,
        competitor_id=payload.competitor_id,
    )


@router.get("/catalog-frequency")
def get_catalog_frequency():
    return dual_scheduler.get_catalog_frequency()


@router.post("/catalog-run-now")
def catalog_run_now(payload: RunNowRequest = RunNowRequest(), user_id: Optional[int] = Query(default=None)):
    launched_by_user_id = resolve_user_id(
        payload_launched_by_user_id=payload.launched_by_user_id,
        query_user_id=user_id,
    )

    print("[SCRAPING_ROUTE] /catalog-run-now launched_by_user_id =", launched_by_user_id, flush=True)

    return {
        "status": "started",
        "message": "Scraping catalogue lancé en arrière-plan.",
        "job": dual_scheduler.run_catalog_now(
            competitor_id=payload.competitor_id,
            launched_by_user_id=launched_by_user_id,
        ),
    }


@router.get("/scheduler-status")
def scheduler_status():
    return dual_scheduler.status()