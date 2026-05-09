from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.repositories.user_repo import UserRepository
from app.schemas.user_schemas import AdminEmailUpdate, UserCreateByAdmin, UserResponse, UserUpdateByAdmin
from app.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_by_admin(
    payload: UserCreateByAdmin,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return AuthService.create_user_by_admin(
        db=db,
        prenom=payload.prenom,
        nom=payload.nom,
        email=payload.email,
        roles=payload.roles,
        request=request,
    )


@router.get("", response_model=List[UserResponse])
def list_users(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return UserRepository.list_all(db)


@router.patch("/{user_id}/email", response_model=UserResponse)
def update_user_email_as_admin(
    user_id: int,
    payload: AdminEmailUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return AuthService.admin_update_user_email(db=db, user_id=user_id, email=payload.email)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    user = UserRepository.get_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdateByAdmin,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return AuthService.admin_update_user(db, user_id, payload.dict(exclude_none=True))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    AuthService.admin_delete_user(db, user_id)


@router.post("/{user_id}/resend-activation")
def resend_activation(user_id: int, request: Request, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return AuthService.admin_resend_activation(db, user_id, request=request)
