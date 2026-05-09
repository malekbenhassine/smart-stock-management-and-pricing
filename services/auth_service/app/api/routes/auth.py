from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.auth_schemas import (
    ActivateAccountRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user_schemas import UserResponse, UserUpdateMe
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/activate")
def activate_account(payload: ActivateAccountRequest, request: Request, db: Session = Depends(get_db)):
    return AuthService.activate_account(
        db=db,
        jeton=payload.jeton,
        mot_de_passe=payload.mot_de_passe,
        confirmation_mot_de_passe=payload.confirmation_mot_de_passe,
        request=request,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    return AuthService.login(db=db, email=payload.email, mot_de_passe=payload.mot_de_passe, request=request)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return AuthService.get_me(current_user)


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdateMe,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return AuthService.update_me(
        db=db,
        current_user=current_user,
        prenom=payload.prenom,
        nom=payload.nom,
        telephone=payload.telephone,
        adresse=payload.adresse,
        date_naissance=payload.date_naissance,
    )


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return AuthService.change_password(
        db=db,
        current_user=current_user,
        mot_de_passe_actuel=payload.mot_de_passe_actuel,
        nouveau_mot_de_passe=payload.nouveau_mot_de_passe,
        confirmation_mot_de_passe=payload.confirmation_mot_de_passe,
        request=request,
    )


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    return AuthService.forgot_password(db=db, email=payload.email, request=request)


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    return AuthService.reset_password(
        db=db,
        jeton=payload.jeton,
        mot_de_passe=payload.mot_de_passe,
        confirmation_mot_de_passe=payload.confirmation_mot_de_passe,
        request=request,
    )
