from fastapi import APIRouter, UploadFile, File, Depends, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...services.csv_import_service import (
    import_single_file,
    import_batch_files,
    get_import_logs_service,
)

router = APIRouter(prefix="/import", tags=["csv-import"])

ACCEPTED_EXTENSIONS = (".csv", ".json", ".xlsx", ".xls")


@router.post("/csv")
async def import_csv(
    file: UploadFile = File(...),
    upsert: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return await import_single_file(file=file, db=db, upsert=upsert)


@router.post("/csv/batch")
async def import_csv_batch(
    files: list[UploadFile] = File(...),
    upsert: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return await import_batch_files(files=files, db=db, upsert=upsert)


@router.get("/logs")
def get_import_logs(
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return get_import_logs_service(limit=limit, db=db)
