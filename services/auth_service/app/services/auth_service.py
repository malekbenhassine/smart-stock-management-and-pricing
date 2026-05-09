import secrets
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.role import UserRole
from app.models.token import TypeJeton
from app.models.user import User
from app.repositories.journal_authentification_repo import JournalAuthentificationRepository
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
    def create_user_by_admin(db: Session, prenom: str, nom: str, email: str, roles: List[UserRole], request: Optional[Request] = None) -> User:
        roles_values = [role.value if isinstance(role, UserRole) else str(role) for role in roles]

        if UserRole.ADMIN.value in roles_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le rôle ADMIN ne peut pas être attribué depuis cet endpoint."
            )

        if not roles_values:
            raise HTTPException(status_code=400, detail="Au moins un rôle est obligatoire.")

        if len(set(roles_values)) != len(roles_values):
            raise HTTPException(status_code=400, detail="Les rôles ne doivent pas être dupliqués.")

        existing = UserRepository.get_by_email(db, email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un utilisateur avec cet email existe déjà."
            )

        utilisateur = UserRepository.create(
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
        expires_at = datetime.utcnow() + timedelta(hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS)

        TokenRepository.create(
            db=db,
            utilisateur_id=utilisateur.id,
            valeur=raw_token,
            type_jeton=TypeJeton.ACTIVATION,
            expire_le=expires_at,
            utilise=False,
        )

        EmailService.send_activation_email(utilisateur.email, nom_affichage(utilisateur), raw_token)

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_EMAIL_ACTIVATION_ENVOYE,
            statut=STATUT_INFORMATION,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Email d'activation envoyé après création du compte par l'administrateur.",
        )

        return utilisateur

    @staticmethod
    def activate_account(db: Session, jeton: str, mot_de_passe: str, confirmation_mot_de_passe: str, request: Optional[Request] = None):
        if mot_de_passe != confirmation_mot_de_passe:
            AuthService.ajouter_journal(
                db=db,
                type_evenement=TYPE_ACTIVATION_COMPTE,
                statut=STATUT_ECHEC,
                request=request,
                message="Confirmation du mot de passe incorrecte pendant l'activation du compte.",
            )
            raise HTTPException(status_code=400, detail="La confirmation du mot de passe ne correspond pas.")

        activation = TokenRepository.get_by_valeur_et_type(db, jeton, TypeJeton.ACTIVATION)
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

        utilisateur = UserRepository.get_by_id(db, activation.utilisateur_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        utilisateur.mot_de_passe_hash = hash_password(mot_de_passe)
        utilisateur.email_verifie = True
        utilisateur.est_actif = True
        utilisateur.doit_changer_mot_de_passe = False
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

        return {"message": "Compte activé avec succès."}

    @staticmethod
    def login(db: Session, email: str, mot_de_passe: str, request: Optional[Request] = None):
        utilisateur = UserRepository.get_by_email(db, email)
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
    def update_me(db: Session, current_user: User, prenom: str, nom: str, telephone: Optional[str], adresse: Optional[str], date_naissance) -> User:
        current_user.prenom = prenom.strip()
        current_user.nom = nom.strip()
        current_user.telephone = telephone
        current_user.adresse = adresse
        current_user.date_naissance = date_naissance

        db.commit()
        db.refresh(current_user)
        return current_user

    @staticmethod
    def admin_update_user_email(db: Session, user_id: int, email: str) -> User:
        existing = UserRepository.get_by_email(db, email)
        if existing and existing.id != user_id:
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé.")

        utilisateur = UserRepository.get_by_id(db, user_id)
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
            raise HTTPException(status_code=400, detail="La confirmation du nouveau mot de passe ne correspond pas.")

        current_user.mot_de_passe_hash = hash_password(nouveau_mot_de_passe)
        current_user.doit_changer_mot_de_passe = False
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
        utilisateur = UserRepository.get_by_email(db, email)

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

        TokenRepository.create(
            db=db,
            utilisateur_id=utilisateur.id,
            valeur=raw_token,
            type_jeton=TypeJeton.REINITIALISATION_MOT_DE_PASSE,
            expire_le=expires_at,
            utilise=False,
        )

        EmailService.send_reset_password_email(utilisateur.email, nom_affichage(utilisateur), raw_token)

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
    def reset_password(db: Session, jeton: str, mot_de_passe: str, confirmation_mot_de_passe: str, request: Optional[Request] = None):
        if mot_de_passe != confirmation_mot_de_passe:
            raise HTTPException(status_code=400, detail="La confirmation du mot de passe ne correspond pas.")

        reset_token = TokenRepository.get_by_valeur_et_type(db, jeton, TypeJeton.REINITIALISATION_MOT_DE_PASSE)
        if not reset_token:
            raise HTTPException(status_code=404, detail="Jeton de réinitialisation introuvable.")

        if reset_token.utilise:
            raise HTTPException(status_code=400, detail="Ce jeton a déjà été utilisé.")

        if reset_token.expire_le < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Le jeton de réinitialisation a expiré.")

        utilisateur = UserRepository.get_by_id(db, reset_token.utilisateur_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        utilisateur.mot_de_passe_hash = hash_password(mot_de_passe)
        utilisateur.doit_changer_mot_de_passe = False
        reset_token.utilise = True

        db.commit()

        AuthService.ajouter_journal(
            db=db,
            type_evenement=TYPE_REINITIALISATION_MOT_DE_PASSE,
            statut=STATUT_SUCCES,
            request=request,
            utilisateur_id=utilisateur.id,
            adresse_email=utilisateur.email,
            message="Mot de passe réinitialisé avec succès.",
        )

        return {"message": "Mot de passe réinitialisé avec succès."}

    @staticmethod
    def admin_update_user(db: Session, user_id: int, payload: dict) -> User:
        utilisateur = UserRepository.get_by_id(db, user_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        if utilisateur.has_role(UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="Impossible de modifier un administrateur.")

        payload.pop("email", None)
        payload.pop("telephone", None)
        payload.pop("adresse", None)
        payload.pop("date_naissance", None)

        if "roles" in payload:
            roles_values = [role.value if isinstance(role, UserRole) else str(role) for role in payload["roles"]]
            if UserRole.ADMIN.value in roles_values:
                raise HTTPException(status_code=400, detail="Le rôle ADMIN ne peut pas être attribué depuis cet endpoint.")
            if not roles_values:
                raise HTTPException(status_code=400, detail="Au moins un rôle est obligatoire.")
            if len(set(roles_values)) != len(roles_values):
                raise HTTPException(status_code=400, detail="Les rôles ne doivent pas être dupliqués.")
            payload["roles"] = roles_values

        if "prenom" in payload and payload["prenom"] is not None:
            payload["prenom"] = payload["prenom"].strip()
        if "nom" in payload and payload["nom"] is not None:
            payload["nom"] = payload["nom"].strip()

        return UserRepository.update(db, utilisateur, **payload)

    @staticmethod
    def admin_delete_user(db: Session, user_id: int) -> None:
        utilisateur = UserRepository.get_by_id(db, user_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
        if utilisateur.has_role(UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="Impossible de supprimer un admin.")
        UserRepository.delete(db, utilisateur)

    @staticmethod
    def admin_resend_activation(db: Session, user_id: int, request: Optional[Request] = None):
        utilisateur = UserRepository.get_by_id(db, user_id)
        if not utilisateur:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
        if utilisateur.est_actif:
            raise HTTPException(status_code=400, detail="Le compte est déjà actif.")

        raw_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS)

        TokenRepository.create(
            db=db,
            utilisateur_id=utilisateur.id,
            valeur=raw_token,
            type_jeton=TypeJeton.ACTIVATION,
            expire_le=expires_at,
            utilise=False,
        )

        EmailService.send_activation_email(utilisateur.email, nom_affichage(utilisateur), raw_token)

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
