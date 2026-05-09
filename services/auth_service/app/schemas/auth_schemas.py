from pydantic import BaseModel, EmailStr, Field

from app.schemas.user_schemas import UserResponse


class LoginRequest(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    utilisateur: UserResponse


class ActivateAccountRequest(BaseModel):
    jeton: str
    mot_de_passe: str = Field(min_length=8)
    confirmation_mot_de_passe: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    mot_de_passe_actuel: str = Field(min_length=8)
    nouveau_mot_de_passe: str = Field(min_length=8)
    confirmation_mot_de_passe: str = Field(min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    jeton: str
    mot_de_passe: str = Field(min_length=8)
    confirmation_mot_de_passe: str = Field(min_length=8)
