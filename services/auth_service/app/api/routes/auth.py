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
        token=payload.token,
        password=payload.password,
        confirm_password=payload.confirm_password,
        request=request,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    return AuthService.login(db=db, email=payload.email, password=payload.password, request=request)


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
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        address=payload.address,
        birth_date=payload.birth_date,
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
        current_password=payload.current_password,
        new_password=payload.new_password,
        confirm_password=payload.confirm_password,
        request=request,
    )


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    return AuthService.forgot_password(db=db, email=payload.email, request=request)


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    return AuthService.reset_password(
        db=db,
        token=payload.token,
        password=payload.password,
        confirm_password=payload.confirm_password,
        request=request,
    )