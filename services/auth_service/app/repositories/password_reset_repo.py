# Conservé uniquement pour éviter les imports cassés si un ancien fichier l'importe encore.
# La vraie logique est maintenant dans app.repositories.token_repo avec la table unique "jeton".
from app.models.token import TypeJeton
from app.repositories.token_repo import TokenRepository


class PasswordResetTokenRepository:
    @staticmethod
    def create(db, **kwargs):
        return TokenRepository.create(
            db=db,
            utilisateur_id=kwargs["user_id"],
            valeur=kwargs["token"],
            type_jeton=TypeJeton.REINITIALISATION_MOT_DE_PASSE,
            expire_le=kwargs["expires_at"],
            utilise=kwargs.get("used", False),
        )

    @staticmethod
    def get_by_token(db, token: str):
        return TokenRepository.get_by_valeur_et_type(
            db, token, TypeJeton.REINITIALISATION_MOT_DE_PASSE
        )
