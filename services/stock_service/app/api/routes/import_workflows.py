from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.schemas.schemas import PostImportWorkflowRequest
from app.services.post_import_workflow_service import run_post_import_workflow_service

router = APIRouter(tags=["imports"])


def _run_post_import_background(
    table_name: str,
    max_products: int,
    product_ids: list[int] | None = None,
):
    db = SessionLocal()

    try:
        run_post_import_workflow_service(
            db=db,
            table_name=table_name,
            max_products=max_products,
            product_ids=product_ids,
        )
    finally:
        db.close()


@router.post("/imports/after-import")
def run_after_import_workflow(
    payload: PostImportWorkflowRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    product_ids = payload.product_ids or []

    # Nettoyage IDs
    product_ids = list(
        dict.fromkeys(
            [int(pid) for pid in product_ids if pid is not None]
        )
    )

    if payload.async_mode:
        background_tasks.add_task(
            _run_post_import_background,
            payload.table_name,
            payload.max_products,
            product_ids,
        )

        return {
            "status": "scheduled",
            "message": "Workflow post-import lancé en arrière-plan.",
            "table": payload.table_name,
            "max_products": payload.max_products,
            "product_ids": product_ids,
            "total_products_to_scan": len(product_ids),
        }

    return run_post_import_workflow_service(
        db=db,
        table_name=payload.table_name,
        max_products=payload.max_products,
        product_ids=product_ids,
    )