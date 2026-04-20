from datetime import datetime, timezone
from sqlalchemy.orm import Session
from ..models.tables import ImportLog


def log_import_bulk(db: Session, entries: list[dict]) -> None:
    """
    Insère tous les logs d'import en un seul commit.
    Chaque entrée : {filename, table, status, rows, error (optionnel)}

    FIX timezone: stocke l'heure UTC correcte.
    - Si la colonne ImportLog.imported_at est TIMESTAMPTZ (PostgreSQL) → on passe timezone-aware
    - Si la colonne est TIMESTAMP sans timezone (SQLite/MySQL) → on passe naive UTC
    Le frontend reçoit une ISO string avec 'Z' ou '+00:00' et new Date() la convertit correctement.
    """
    now = datetime.now(timezone.utc)  # heure UTC exacte, timezone-aware
    db.add_all(
        ImportLog(
            filename=e["filename"],
            table_name=e["table"],
            status=e["status"],
            rows_imported=e.get("rows", 0),
            error_detail=e.get("error"),
            imported_at=now,
        )
        for e in entries
    )
    db.commit()
