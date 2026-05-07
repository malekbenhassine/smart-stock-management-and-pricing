import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.role import UserRole
from app.models.user import User
from app.repositories.journal_authentification_repo import JournalAuthentificationRepository
from app.repositories.password_reset_repo import PasswordResetTokenRepository
from app.repositories.token_repo import TokenRepository
from app.repositories.user_repo import UserRepository
from app.services.email_service import EmailService


TYPE_CONNEXION = "CONNEXION"
TYPE_ACTIVATION_COMPTE = "ACTIVATION_COMPTE"
TYPE_DEMANDE_REINITIALISATION_MOT_DE_PASSE = "DEMANDE_REINITIALISATION_MOT_DE_PASSE"
TYPE_REINITIALISATION_MOT_DE_PASSE = "REINITIALISATION_MOT_DE_PASSE"
TYPE_CHANGEMENT_MOT_DE_PASSE = "CHANGEMENT_MOT_DE_PASSE"
TYPE_EMAIL_ACTIVATION_ENVOYE = "EMAIL_ACTIVATION_ENVOYE"
TYPE_EMAIL_ACTIVATION_RENVOYE = "EMAIL_ACTIVATION_RENVOYE"

STATUT_SUCCES = "SUCCES"
STATUT_ECHEC = "ECHEC"
STATUT_INFORMATION = "INFORMATION"


def split_full_name(full_name: str) -> tuple[str, str]:
    value = (full_name or "").strip()
    parts = value.split()

    if not parts:
        return "", ""

    if len(parts) == 1:
        return parts[0], ""

    return parts[0], " ".join(parts[1:])


def extraire_adresse_ip(request: Optional[Request]) -> Optional[str]:
    if not request:
        return None

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client:
        return request.client.host

    return None


def extraire_navigateur(request: Optional[Request]) -> Optional[str]:
    if not request:
        return None
    return request.headers.get("user-agent")


class AuthService:
    @staticmethod
    def ajouter_journal(
        db: Session,
        type_evenement: str,
        statut: str,
        request: Optional[Request] = None,
        utilisateur_id: Optional[int] = None,
        adresse_email: Optional[str] = None,
        message: Optional[str] = None,
    ):
        try:
            return JournalAuthentificationRepository.creer(
                db=db,
                type_evenement=type_evenement,
                statut=statut,
                utilisateur_id=utilisateur_id,
                adresse_email=adresse_email,
                adresse_ip=extraire_adresse_ip(request),
                navigateur=extraire_navigateur(request),
                message=message,
            )
        except Exception:
            db.rollback()
            return None

    @staticmethod
    def create_user_by_admin(db: Session, full_name: str, email: str, role: UserRole, request: Optional[Request] = None) -> User:
        if role == UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="L'admin ne peut pas être créé via cet endpoint."
            )

        existing = UserRepository.get_by_email(db, email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un utilisateur avec cet email existe déjà."
            )

        first_name, last_name = split_full_name(full_name)

        user = UserRepository.create(
            db,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password_hash=None,
            role=role,
            phone=None,
            address=None,
            birth_date=None,
            is_active=False,
            email_verified=False,
        )

        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS)

        TokenRepository.create(
            db,
            user_id=user.id,
            token=raw_token,
            expires_at=expires_at,
            used=False,
        )

        EmailService.send_activation_email(user.email, user.full_name, raw_token)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_EMAIL_ACTIVATION_ENVOYE,
            statut=STATUT_INFORMATION,
            request=request,
            utilisateur_id=user.id,
            adresse_email=user.email,
            message="Email d'activation envoyé après création du compte par l'administrateur.",
        )

        return user

    @staticmethod
    def activate_account(db: Session, token: str, password: str, confirm_password: str, request: Optional[Request] = None):
        if password != confirm_password:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                message="Confirmation du mot de passe incorrecte pendant l'activation du compte.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La confirmation du mot de passe ne correspond pas."
            )

        activation = TokenRepository.get_by_token(db, token)
        if not activation:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                message="Token d'activation introuvable.",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token d'activation introuvable."
            )

        if activation.used:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=activation.user_id,
                message="Tentative d'activation avec un token déjà utilisé.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce token a déjà été utilisé."
            )

        if activation.expires_at < datetime.utcnow():
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=activation.user_id,
                message="Tentative d'activation avec un token expiré.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le token d'activation a expiré."
            )

        user = UserRepository.get_by_id(db, activation.user_id)
        if not user:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=activation.user_id,
                message="Utilisateur introuvable pendant l'activation du compte.",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Utilisateur introuvable."
            )

        user.password_hash = hash_password(password)
        user.email_verified = True
        user.is_active = True
        activation.used = True

        db.commit()
        db.refresh(user)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_ACTIVATION_COMPTE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=user.id,
            adresse_email=user.email,
            message="Compte activé avec succès.",
        )

        return {"message": "Compte activé avec succès."}

    @staticmethod
    def login(db: Session, email: str, password: str, request: Optional[Request] = None):
        user = UserRepository.get_by_email(db, email)
        if not user:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CONNEXION,
                statut=STATUT_ECHEC,
                request=request,
                adresse_email=email,
                message="Tentative de connexion avec un email inexistant.",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe invalide."
            )

        if not user.password_hash:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CONNEXION,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=user.id,
                adresse_email=user.email,
                message="Tentative de connexion avant activation du compte.",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Compte non activé."
            )

        if not user.email_verified or not user.is_active:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CONNEXION,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=user.id,
                adresse_email=user.email,
                message="Tentative de connexion avec un compte non vérifié ou inactif.",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Compte non vérifié ou inactif."
            )

        if not verify_password(password, user.password_hash):
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CONNEXION,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=user.id,
                adresse_email=user.email,
                message="Mot de passe incorrect pendant la connexion.",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe invalide."
            )

        token = create_access_token(subject=user.id)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_CONNEXION,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=user.id,
            adresse_email=user.email,
            message="Connexion réussie.",
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user,
        }

    @staticmethod
    def get_me(current_user: User) -> User:
        return current_user

    @staticmethod
    def update_me(
        db: Session,
        current_user: User,
        first_name: str,
        last_name: str,
        phone: Optional[str],
        address: Optional[str],
        birth_date,
    ) -> User:
        current_user.first_name = first_name.strip()
        current_user.last_name = last_name.strip()
        current_user.full_name = f"{current_user.first_name} {current_user.last_name}".strip()
        current_user.phone = phone
        current_user.address = address
        current_user.birth_date = birth_date

        db.commit()
        db.refresh(current_user)
        return current_user

    @staticmethod
    def admin_update_user_email(db: Session, user_id: int, email: str) -> User:
        existing = UserRepository.get_by_email(db, email)
        if existing and existing.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cet email est déjà utilisé."
            )

        user = UserRepository.get_by_id(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Utilisateur introuvable."
            )

        user.email = email
        user.email_verified = True

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def change_password(
        db: Session,
        current_user: User,
        current_password: str,
        new_password: str,
        confirm_password: str,
        request: Optional[Request] = None,
    ):
        if not verify_password(current_password, current_user.password_hash):
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CHANGEMENT_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=current_user.id,
                adresse_email=current_user.email,
                message="Mot de passe actuel incorrect.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe actuel incorrect."
            )

        if new_password != confirm_password:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CHANGEMENT_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=current_user.id,
                adresse_email=current_user.email,
                message="Confirmation du nouveau mot de passe incorrecte.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La confirmation du nouveau mot de passe ne correspond pas."
            )

        current_user.password_hash = hash_password(new_password)
        db.commit()

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_CHANGEMENT_MOT_DE_PASSE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=current_user.id,
            adresse_email=current_user.email,
            message="Mot de passe modifié avec succès.",
        )

        return {"message": "Mot de passe modifié avec succès."}

    @staticmethod
    def forgot_password(db: Session, email: str, request: Optional[Request] = None):
        user = UserRepository.get_by_email(db, email)

        if not user:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_DEMANDE_REINITIALISATION_MOT_DE_PASSE,
                statut=STATUT_INFORMATION,
                request=request,
                adresse_email=email,
                message="Demande de réinitialisation reçue pour un email inexistant. Réponse neutre retournée.",
            )
            return {
                "message": "Si cet email existe, un lien de réinitialisation a été envoyé."
            }

        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=1)

        PasswordResetTokenRepository.create(
            db,
            user_id=user.id,
            token=raw_token,
            expires_at=expires_at,
            used=False,
        )

        EmailService.send_reset_password_email(user.email, user.full_name, raw_token)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_DEMANDE_REINITIALISATION_MOT_DE_PASSE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=user.id,
            adresse_email=user.email,
            message="Email de réinitialisation du mot de passe envoyé.",
        )

        return {
            "message": "Si cet email existe, un lien de réinitialisation a été envoyé."
        }

    @staticmethod
    def reset_password(db: Session, token: str, password: str, confirm_password: str, request: Optional[Request] = None):
        if password != confirm_password:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                message="Confirmation du mot de passe incorrecte pendant la réinitialisation.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La confirmation du mot de passe ne correspond pas."
            )

        reset_token = PasswordResetTokenRepository.get_by_token(db, token)
        if not reset_token:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                message="Token de réinitialisation introuvable.",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token de réinitialisation introuvable."
            )

        if reset_token.used:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=reset_token.user_id,
                message="Tentative de réinitialisation avec un token déjà utilisé.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce token a déjà été utilisé."
            )

        if reset_token.expires_at < datetime.utcnow():
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=reset_token.user_id,
                message="Tentative de réinitialisation avec un token expiré.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le token de réinitialisation a expiré."
            )

        user = UserRepository.get_by_id(db, reset_token.user_id)
        if not user:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=reset_token.user_id,
                message="Utilisateur introuvable pendant la réinitialisation.",
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Utilisateur introuvable."
            )

        user.password_hash = hash_password(password)
        reset_token.used = True

        db.commit()

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=user.id,
            adresse_email=user.email,
            message="Mot de passe réinitialisé avec succès.",
        )

        return {"message": "Mot de passe réinitialisé avec succès."}
    
    @staticmethod
    def admin_update_user(db: Session, user_id: int, payload: dict) -> User:
        user = UserRepository.get_by_id(db, user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Utilisateur introuvable."
            )

        if user.role == UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Impossible de modifier un administrateur."
            )

        payload.pop("email", None)
        payload.pop("phone", None)
        payload.pop("address", None)
        payload.pop("birth_date", None)
        payload.pop("first_name", None)
        payload.pop("last_name", None)

        if payload.get("full_name"):
            first_name, last_name = split_full_name(payload["full_name"])
            payload["first_name"] = first_name
            payload["last_name"] = last_name

        return UserRepository.update(db, user, **payload)
    
    @staticmethod
    def admin_delete_user(db: Session, user_id: int) -> None:
        user = UserRepository.get_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
        if user.role == UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Impossible de supprimer un admin.")
        UserRepository.delete(db, user)

    @staticmethod
    def admin_resend_activation(db: Session, user_id: int, request: Optional[Request] = None):
        user = UserRepository.get_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
        if user.is_active:
            raise HTTPException(status_code=400, detail="Le compte est déjà actif.")
        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS)
        TokenRepository.create(db, user_id=user.id, token=raw_token, expires_at=expires_at, used=False)
        EmailService.send_activation_email(user.email, user.full_name, raw_token)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_EMAIL_ACTIVATION_RENVOYE,
            statut=STATUT_INFORMATION,
            request=request,
            utilisateur_id=user.id,
            adresse_email=user.email,
            message="Email d'activation renvoyé par l'administrateur.",
        )

        return {"message": "Email d'activation renvoyé."}
