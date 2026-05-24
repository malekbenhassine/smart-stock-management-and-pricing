import secrets
from datetime import datetime, timedelta
from functools import lru_cache
from types import ModuleType
from typing import Optional, List, Any, Type

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.role import UserRole
from app.models.token import TypeJeton
from app.models.user import User
from app.models import token as token_models
from app.models import journal_authentification as journal_models
from app.services.email_service import EmailService
from app.services.auth_alert_service import (
    emit_account_created_alert,
    emit_account_activated_alert,
    emit_password_changed_alert,
)

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


def nom_affichage(utilisateur: User) -> str:
    return f"{utilisateur.prenom or ''} {utilisateur.nom or ''}".strip()


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


def _find_model_class(module: ModuleType, required_attrs: set[str]) -> Type[Any]:
    for value in vars(module).values():
        if isinstance(value, type) and all(hasattr(value, attr) for attr in required_attrs):
            return value

    raise RuntimeError(
        f"Modèle introuvable dans {module.__name__}. "
        f"Attributs attendus : {', '.join(sorted(required_attrs))}"
    )


@lru_cache(maxsize=1)
def get_token_model() -> Type[Any]:
    return _find_model_class(
        token_models,
        {"utilisateur_id", "valeur", "type_jeton", "expire_le", "utilise"},
    )


@lru_cache(maxsize=1)
def get_journal_model() -> Type[Any]:
    return _find_model_class(
        journal_models,
        {
            "type_evenement",
            "statut",
            "utilisateur_id",
            "adresse_email",
            "adresse_ip",
            "navigateur",
            "message",
        },
    )


class AuthService:
    # =========================
    # Accès DB direct via service
    # =========================

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> User | None:
        return db.scalar(select(User).where(User.id == user_id))

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> User | None:
        return db.scalar(select(User).where(User.email == email))

    @staticmethod
    def list_users(db: Session) -> list[User]:
        return db.scalars(select(User).order_by(User.id.desc())).all()

    @staticmethod
    def create_user(db: Session, **kwargs) -> User:
        utilisateur = User(**kwargs)
        db.add(utilisateur)
        db.commit()
        db.refresh(utilisateur)
        return utilisateur

    @staticmethod
    def update_user_instance(db: Session, utilisateur: User, **kwargs) -> User:
        for key, value in kwargs.items():
            setattr(utilisateur, key, value)

        db.commit()
        db.refresh(utilisateur)
        return utilisateur

    @staticmethod
    def delete_user_instance(db: Session, utilisateur: User) -> None:
        db.delete(utilisateur)
        db.commit()

    @staticmethod
    def create_token(
        db: Session,
        *,
        utilisateur_id: int,
        valeur: str,
        type_jeton: TypeJeton,
        expire_le: datetime,
        utilise: bool = False,
    ):
        TokenModel = get_token_model()

        token = TokenModel(
            utilisateur_id=utilisateur_id,
            valeur=valeur,
            type_jeton=type_jeton,
            expire_le=expire_le,
            utilise=utilise,
        )

        db.add(token)
        db.commit()
        db.refresh(token)

        return token

    @staticmethod
    def get_token_by_value_and_type(
        db: Session,
        valeur: str,
        type_jeton: TypeJeton,
    ):
        TokenModel = get_token_model()

        return db.scalar(
            select(TokenModel).where(
                TokenModel.valeur == valeur,
                TokenModel.type_jeton == type_jeton,
            )
        )

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
            JournalModel = get_journal_model()

            journal = JournalModel(
                type_evenement=type_evenement,
                statut=statut,
                utilisateur_id=utilisateur_id,
                adresse_email=adresse_email,
                adresse_ip=extraire_adresse_ip(request),
                navigateur=extraire_navigateur(request),
                message=message,
            )

            db.add(journal)
            db.commit()
            db.refresh(journal)

            return journal

        except Exception:
            db.rollback()
            return None

    # =========================
    # Métier Auth
    # =========================

    @staticmethod
    def create_user_by_admin(
        db: Session,
        prenom: str,
        nom: str,
        email: str,
        roles: List[UserRole],
        request: Optional[Request] = None,
    ) -> User:
        roles_values = [
            role.value if isinstance(role, UserRole) else str(role)
            for role in roles
        ]

        if UserRole.ADMIN.value in roles_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le rôle ADMIN ne peut pas être attribué depuis cet endpoint.",
            )

        if not roles_values:
            raise HTTPException(status_code=400, detail="Au moins un rôle est obligatoire.")

        if len(set(roles_values)) != len(roles_values):
            raise HTTPException(status_code=400, detail="Les rôles ne doivent pas être dupliqués.")

        existing = AuthService.get_user_by_email(db, email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un utilisateur avec cet email existe déjà.",
            )

        utilisateur = AuthService.create_user(
            db,
            prenom=prenom.strip(),
            nom=nom.strip(),
            email=email,
            mot_de_passe_hash=None,
            roles=roles_values,
            telephone=None,
            adresse=None,
            date_naissance=None,
            est_actif=False,
            email_verifie=False,
            doit_changer_mot_de_passe=False,
        )

        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(
            hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS
        )

        AuthService.create_token(
            db=db,
            utilisateur_id=utilisateur.id,
            valeur=raw_token,
            type_jeton=TypeJeton.ACTIVATION,
            expire_le=expires_at,
            utilise=False,
        )

        EmailService.send_activation_email(
            utilisateur.email,
            nom_affichage(utilisateur),
            raw_token,
        )

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_EMAIL_ACTIVATION_ENVOYE,
            statut=STATUT_INFORMATION,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Email d'activation envoyé après création du compte par l'administrateur.",
        )

        emit_account_created_alert(utilisateur)

        return utilisateur

    @staticmethod
    def activate_account(
        db: Session,
        jeton: str,
        mot_de_passe: str,
        confirmation_mot_de_passe: str,
        request: Optional[Request] = None,
    ):
        if mot_de_passe != confirmation_mot_de_passe:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                message="Confirmation du mot de passe incorrecte pendant l'activation du compte.",
            )

            raise HTTPException(
                status_code=400,
                detail="La confirmation du mot de passe ne correspond pas.",
            )

        activation = AuthService.get_token_by_value_and_type(
            db,
            jeton,
            TypeJeton.ACTIVATION,
        )

        if not activation:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                message="Jeton d'activation introuvable.",
            )

            raise HTTPException(status_code=404, detail="Jeton d'activation introuvable.")

        if activation.utilise:
            raise HTTPException(status_code=400, detail="Ce jeton a déjà été utilisé.")

        if activation.expire_le < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Le jeton d'activation a expiré.")

        utilisateur = AuthService.get_user_by_id(db, activation.utilisateur_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        utilisateur.mot_de_passe_hash = hash_password(mot_de_passe)
        utilisateur.email_verifie = True
        utilisateur.est_actif = True
        utilisateur.doit_changer_mot_de_passe = False

        utilisateur.mot_de_passe_modifie_le = datetime.utcnow()

        activation.utilise = True

        db.commit()
        db.refresh(utilisateur)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_ACTIVATION_COMPTE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Compte activé avec succès.",
        )

        emit_account_activated_alert(utilisateur)
        emit_password_changed_alert(utilisateur)

        return {"message": "Compte activé avec succès."}

    @staticmethod
    def login(
        db: Session,
        email: str,
        mot_de_passe: str,
        request: Optional[Request] = None,
    ):
        utilisateur = AuthService.get_user_by_email(db, email)

        if not utilisateur:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CONNEXION,
                statut=STATUT_ECHEC,
                request=request,
                adresse_email=email,
                message="Tentative de connexion avec un email inexistant.",
            )

            raise HTTPException(status_code=401, detail="Email ou mot de passe invalide.")

        if not utilisateur.mot_de_passe_hash:
            raise HTTPException(status_code=401, detail="Compte non activé.")

        if not utilisateur.email_verifie or not utilisateur.est_actif:
            raise HTTPException(status_code=403, detail="Compte non vérifié ou inactif.")

        if not verify_password(mot_de_passe, utilisateur.mot_de_passe_hash):
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CONNEXION,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=utilisateur.id,
                adresse_email=utilisateur.email,
                message="Mot de passe incorrect pendant la connexion.",
            )

            raise HTTPException(status_code=401, detail="Email ou mot de passe invalide.")

        token = create_access_token(subject=utilisateur.id)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_CONNEXION,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Connexion réussie.",
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "utilisateur": utilisateur,
        }

    @staticmethod
    def get_me(current_user: User) -> User:
        return current_user

    @staticmethod
    def update_me(
        db: Session,
        current_user: User,
        prenom: str,
        nom: str,
        telephone: Optional[str],
        adresse: Optional[str],
        date_naissance,
    ) -> User:
        current_user.prenom = prenom.strip()
        current_user.nom = nom.strip()
        current_user.telephone = telephone
        current_user.adresse = adresse
        current_user.date_naissance = date_naissance

        db.commit()
        db.refresh(current_user)

        return current_user

    @staticmethod
    def admin_update_user_email(
        db: Session,
        user_id: int,
        email: str,
    ) -> User:
        existing = AuthService.get_user_by_email(db, email)
        if existing and existing.id != user_id:
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé.")

        utilisateur = AuthService.get_user_by_id(db, user_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        utilisateur.email = email
        utilisateur.email_verifie = True

        db.commit()
        db.refresh(utilisateur)

        return utilisateur

    @staticmethod
    def change_password(
        db: Session,
        current_user: User,
        mot_de_passe_actuel: str,
        nouveau_mot_de_passe: str,
        confirmation_mot_de_passe: str,
        request: Optional[Request] = None,
    ):
        if not verify_password(mot_de_passe_actuel, current_user.mot_de_passe_hash):
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_CHANGEMENT_MOT_DE_PASSE,
                statut=STATUT_ECHEC,
                request=request,
                utilisateur_id=current_user.id,
                adresse_email=current_user.email,
                message="Mot de passe actuel incorrect.",
            )

            raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect.")

        if nouveau_mot_de_passe != confirmation_mot_de_passe:
            raise HTTPException(
                status_code=400,
                detail="La confirmation du nouveau mot de passe ne correspond pas.",
            )

        current_user.mot_de_passe_hash = hash_password(nouveau_mot_de_passe)
        current_user.doit_changer_mot_de_passe = False

        current_user.mot_de_passe_modifie_le = datetime.utcnow()

        db.commit()
        db.refresh(current_user)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_CHANGEMENT_MOT_DE_PASSE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=current_user.id,
            adresse_email=current_user.email,
            message="Mot de passe modifié avec succès.",
        )

        emit_password_changed_alert(current_user)

        return {"message": "Mot de passe modifié avec succès."}

    @staticmethod
    def forgot_password(
        db: Session,
        email: str,
        request: Optional[Request] = None,
    ):
        utilisateur = AuthService.get_user_by_email(db, email)

        if not utilisateur:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_DEMANDE_REINITIALISATION_MOT_DE_PASSE,
                statut=STATUT_INFORMATION,
                request=request,
                adresse_email=email,
                message="Demande de réinitialisation reçue pour un email inexistant. Réponse neutre retournée.",
            )

            return {"message": "Si cet email existe, un lien de réinitialisation a été envoyé."}

        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=1)

        AuthService.create_token(
            db=db,
            utilisateur_id=utilisateur.id,
            valeur=raw_token,
            type_jeton=TypeJeton.REINITIALISATION_MOT_DE_PASSE,
            expire_le=expires_at,
            utilise=False,
        )

        EmailService.send_reset_password_email(
            utilisateur.email,
            nom_affichage(utilisateur),
            raw_token,
        )

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_DEMANDE_REINITIALISATION_MOT_DE_PASSE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Email de réinitialisation du mot de passe envoyé.",
        )

        return {"message": "Si cet email existe, un lien de réinitialisation a été envoyé."}

    @staticmethod
    def reset_password(
        db: Session,
        jeton: str,
        mot_de_passe: str,
        confirmation_mot_de_passe: str,
        request: Optional[Request] = None,
    ):
        if mot_de_passe != confirmation_mot_de_passe:
            raise HTTPException(
                status_code=400,
                detail="La confirmation du mot de passe ne correspond pas.",
            )

        reset_token = AuthService.get_token_by_value_and_type(
            db,
            jeton,
            TypeJeton.REINITIALISATION_MOT_DE_PASSE,
        )

        if not reset_token:
            raise HTTPException(status_code=404, detail="Jeton de réinitialisation introuvable.")

        if reset_token.utilise:
            raise HTTPException(status_code=400, detail="Ce jeton a déjà été utilisé.")

        if reset_token.expire_le < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Le jeton de réinitialisation a expiré.")

        utilisateur = AuthService.get_user_by_id(db, reset_token.utilisateur_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        utilisateur.mot_de_passe_hash = hash_password(mot_de_passe)
        utilisateur.doit_changer_mot_de_passe = False

        utilisateur.mot_de_passe_modifie_le = datetime.utcnow()

        reset_token.utilise = True

        db.commit()
        db.refresh(utilisateur)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Mot de passe réinitialisé avec succès.",
        )

        emit_password_changed_alert(utilisateur)

        return {"message": "Mot de passe réinitialisé avec succès."}

    @staticmethod
    def admin_update_user(
        db: Session,
        user_id: int,
        payload: dict,
    ) -> User:
        utilisateur = AuthService.get_user_by_id(db, user_id)

        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        if utilisateur.has_role(UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="Impossible de modifier un administrateur.")

        payload.pop("email", None)
        payload.pop("telephone", None)
        payload.pop("adresse", None)
        payload.pop("date_naissance", None)

        if "roles" in payload:
            roles_values = [
                role.value if isinstance(role, UserRole) else str(role)
                for role in payload["roles"]
            ]

            if UserRole.ADMIN.value in roles_values:
                raise HTTPException(
                    status_code=400,
                    detail="Le rôle ADMIN ne peut pas être attribué depuis cet endpoint.",
                )

            if not roles_values:
                raise HTTPException(status_code=400, detail="Au moins un rôle est obligatoire.")

            if len(set(roles_values)) != len(roles_values):
                raise HTTPException(status_code=400, detail="Les rôles ne doivent pas être dupliqués.")

            payload["roles"] = roles_values

        if "prenom" in payload and payload["prenom"] is not None:
            payload["prenom"] = payload["prenom"].strip()

        if "nom" in payload and payload["nom"] is not None:
            payload["nom"] = payload["nom"].strip()

        return AuthService.update_user_instance(db, utilisateur, **payload)

    @staticmethod
    def list_journaux_authentification(db: Session, limite: int = 100):
        JournalModel = get_journal_model()

        return db.scalars(
            select(JournalModel)
            .order_by(JournalModel.cree_le.desc())
            .limit(limite)
        ).all()
    
    @staticmethod
    def admin_delete_user(
        db: Session,
        user_id: int,
    ) -> None:
        utilisateur = AuthService.get_user_by_id(db, user_id)

        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        if utilisateur.has_role(UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="Impossible de supprimer un admin.")

        AuthService.delete_user_instance(db, utilisateur)

    @staticmethod
    def admin_resend_activation(
        db: Session,
        user_id: int,
        request: Optional[Request] = None,
    ):
        utilisateur = AuthService.get_user_by_id(db, user_id)

        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        if utilisateur.est_actif:
            raise HTTPException(status_code=400, detail="Le compte est déjà actif.")

        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(
            hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS
        )

        AuthService.create_token(
            db=db,
            utilisateur_id=utilisateur.id,
            valeur=raw_token,
            type_jeton=TypeJeton.ACTIVATION,
            expire_le=expires_at,
            utilise=False,
        )

        EmailService.send_activation_email(
            utilisateur.email,
            nom_affichage(utilisateur),
            raw_token,
        )

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_EMAIL_ACTIVATION_RENVOYE,
            statut=STATUT_INFORMATION,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Email d'activation renvoyé par l'administrateur.",
        )

        return {"message": "Email d'activation renvoyé."}