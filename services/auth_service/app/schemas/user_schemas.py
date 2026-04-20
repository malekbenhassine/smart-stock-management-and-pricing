from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.models.role import UserRole


class UserCreateByAdmin(BaseModel):
    full_name: str
    email: EmailStr
    role: UserRole


class UserResponse(BaseModel):
    id: int
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: EmailStr
    role: UserRole
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[date] = None
    is_active: bool
    email_verified: bool

    class Config:
        orm_mode = True


class UserUpdateMe(BaseModel):
    first_name: str
    last_name: str
    phone: Optional[str] = None
    address: Optional[str] = None
    birth_date: Optional[date] = None


class AdminEmailUpdate(BaseModel):
    email: EmailStr
    
class UserUpdateByAdmin(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None  