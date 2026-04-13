from datetime import datetime
from sqlalchemy.orm import Session
from ..models.tables import ImportLog


def log_import(
    db: Session,
    filename: str,
    table_name: str,
    status: str,
    rows: int = 0,
    error: str | None = None,
):
    db.add(
        ImportLog(
            filename=filename,
            table_name=table_name,
            status=status,
            rows_imported=rows,
            error_detail=error,
            imported_at=datetime.utcnow(),
        )
    )
    db.commit()