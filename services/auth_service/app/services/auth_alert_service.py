from datetime import datetime
from typing import Any

from app.services.alert_event_client import emit_alert_event


def get_user_full_name(user: Any) -> str:
    return f"{getattr(user, 'prenom', '') or ''} {getattr(user, 'nom', '') or ''}".strip() or getattr(user, "email", "Utilisateur")


def emit_account_created_alert(user: Any) -> None:
    emit_alert_event(
        event_type="ACCOUNT_CREATED",
        source_service="auth_service",
        user_id=user.id,
        user_email=user.email,
        user_role=",".join(user.roles or []),
        metadata={
            "user_id": user.id,
            "email": user.email,
            "nom": user.nom,
            "prenom": user.prenom,
            "full_name": get_user_full_name(user),
            "roles": user.roles or [],
        },
    )


def emit_account_activated_alert(user: Any) -> None:
    emit_alert_event(
        event_type="ACCOUNT_ACTIVATED",
        source_service="auth_service",
        user_id=user.id,
        user_email=user.email,
        user_role=",".join(user.roles or []),
        metadata={
            "user_id": user.id,
            "email": user.email,
            "nom": user.nom,
            "prenom": user.prenom,
            "full_name": get_user_full_name(user),
            "status_from": "INACTIVE",
            "status_to": "ACTIVE",
        },
    )


def emit_password_changed_alert(user: Any) -> None:
    emit_alert_event(
        event_type="PASSWORD_CHANGED",
        source_service="auth_service",
        user_id=user.id,
        user_email=user.email,
        user_role=",".join(user.roles or []),
        metadata={
            "user_id": user.id,
            "email": user.email,
            "nom": user.nom,
            "prenom": user.prenom,
            "full_name": get_user_full_name(user),
            "mot_de_passe_modifie_le": str(getattr(user, "mot_de_passe_modifie_le", datetime.utcnow())),
            "password_updated_at": str(getattr(user, "mot_de_passe_modifie_le", datetime.utcnow())),
        },
    )