from sqlalchemy.orm import Session

from app.models.role import UserRole
from app.models.user import User


def normaliser_kwargs_utilisateur(kwargs: dict) -> dict:
    mapping = {
        "first_name": "prenom",
        "last_name": "nom",
        "password_hash": "mot_de_passe_hash",
        "phone": "telephone",
        "birth_date": "date_naissance",
        "is_active": "est_actif",
        "email_verified": "email_verifie",
    }
    for old_key, new_key in mapping.items():
        if old_key in kwargs:
            kwargs[new_key] = kwargs.pop(old_key)

    # Compatibilité avec les anciens appels qui envoyaient full_name/nom_complet.
    nom_complet = kwargs.pop("full_name", None) or kwargs.pop("nom_complet", None)
    if nom_complet and ("prenom" not in kwargs or "nom" not in kwargs):
        parts = str(nom_complet).strip().split()
        kwargs.setdefault("prenom", parts[0] if parts else "")
        kwargs.setdefault("nom", " ".join(parts[1:]) if len(parts) > 1 else "")

    # Compatibilité avec l'ancien champ role unique.
    if "role" in kwargs and "roles" not in kwargs:
        role = kwargs.pop("role")
        if isinstance(role, UserRole):
            kwargs["roles"] = [role.value]
        else:
            kwargs["roles"] = [str(role)]

    if "roles" in kwargs and kwargs["roles"] is not None:
        kwargs["roles"] = [role.value if isinstance(role, UserRole) else str(role) for role in kwargs["roles"]]

    return kwargs


class UserRepository:
    @staticmethod
    def get_by_email(db: Session, email: str):
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_by_id(db: Session, user_id: int):
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def create(db: Session, **kwargs):
        kwargs = normaliser_kwargs_utilisateur(kwargs)
        user = User(**kwargs)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def list_all(db: Session):
        return db.query(User).order_by(User.id.desc()).all()

    @staticmethod
    def update(db: Session, user: User, **kwargs) -> User:
        kwargs = normaliser_kwargs_utilisateur(kwargs)
        for key, value in kwargs.items():
            if value is not None:
                setattr(user, key, value)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def delete(db: Session, user: User) -> None:
        db.delete(user)
        db.commit()
