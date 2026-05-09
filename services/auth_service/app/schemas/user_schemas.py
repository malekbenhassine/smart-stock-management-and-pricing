from datetime import date
from typing import List, Optional

from pydantic import BaseModel, EmailStr, validator

from app.models.role import UserRole


class UserCreateByAdmin(BaseModel):
    prenom: str
    nom: str
    email: EmailStr
    roles: List[UserRole]

    @validator("roles")
    def roles_obligatoires(cls, value):
        if not value:
            raise ValueError("Au moins un rôle est obligatoire.")
        if len(set(value)) != len(value):
            raise ValueError("Les rôles ne doivent pas être dupliqués.")
        return value


class UserResponse(BaseModel):
    id: int
    prenom: str
    nom: str
    email: EmailStr
    roles: List[UserRole]
    telephone: Optional[str] = None
    adresse: Optional[str] = None
    date_naissance: Optional[date] = None
    est_actif: bool
    email_verifie: bool
    doit_changer_mot_de_passe: bool

    class Config:
        orm_mode = True


class UserUpdateMe(BaseModel):
    prenom: str
    nom: str
    telephone: Optional[str] = None
    adresse: Optional[str] = None
    date_naissance: Optional[date] = None


class AdminEmailUpdate(BaseModel):
    email: EmailStr


class UserUpdateByAdmin(BaseModel):
    prenom: Optional[str] = None
    nom: Optional[str] = None
    roles: Optional[List[UserRole]] = None
    est_actif: Optional[bool] = None

    @validator("roles")
    def roles_non_vides_si_envoyes(cls, value):
        if value is not None and not value:
            raise ValueError("La liste des rôles ne peut pas être vide.")
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Les rôles ne doivent pas être dupliqués.")
        return value
