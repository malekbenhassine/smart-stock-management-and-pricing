from fastapi import APIRouter

from app.schemas.schemas import (
    ScrapingSchedulerConfigIn,
    ScrapingSchedulerRunNowIn,
)
from app.services.scraping_scheduler_service import scraping_scheduler_manager

router = APIRouter(prefix="/scraping/scheduler", tags=["scraping-scheduler"])


@router.get("/status")
def get_scheduler_status():
    return scraping_scheduler_manager.status()


@router.post("/config")
def update_scheduler_config(payload: ScrapingSchedulerConfigIn):
    return scraping_scheduler_manager.update_config(
        enabled=payload.enabled,
        schedule_mode=payload.schedule_mode,
        run_time=payload.run_time,
        interval_minutes=payload.interval_minutes,
        product_limit=payload.product_limit,
    )


@router.post("/start")
def start_scheduler():
    scraping_scheduler_manager.start_loop()
    return scraping_scheduler_manager.update_config(enabled=True)


@router.post("/stop")
def stop_scheduler():
    return scraping_scheduler_manager.update_config(enabled=False)


@router.post("/run-now")
def run_scheduler_now(payload: ScrapingSchedulerRunNowIn):
    return scraping_scheduler_manager.run_once_background(
        trigger="manual",
        product_limit=payload.product_limit,
    )


@router.get("/runs")
def get_scheduler_runs():
    status = scraping_scheduler_manager.status()

    return {
        "status": "success",
        "runs": status.get("runs_history", []),
    }
