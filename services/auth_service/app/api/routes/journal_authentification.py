from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.services.auth_service import AuthService
from app.schemas.journal_authentification_schemas import JournalAuthentificationResponse

router = APIRouter(prefix="/auth/journal", tags=["journal-authentification"])


@router.get("", response_model=List[JournalAuthentificationResponse])
def lister_journal_authentification(
    limite: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return AuthService.list_journaux_authentification(db=db, limite=limite)