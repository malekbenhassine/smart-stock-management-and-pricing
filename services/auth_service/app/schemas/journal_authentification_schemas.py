from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class JournalAuthentificationResponse(BaseModel):
    id: int
    type_evenement: str
    statut: str
    utilisateur_id: Optional[int] = None
    adresse_email: Optional[EmailStr] = None
    adresse_ip: Optional[str] = None
    navigateur: Optional[str] = None
    message: Optional[str] = None
    cree_le: datetime

    class Config:
        orm_mode = True
