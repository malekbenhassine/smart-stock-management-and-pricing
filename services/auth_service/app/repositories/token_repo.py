from sqlalchemy.orm import Session

from app.models.token import Token, TypeJeton


class TokenRepository:
    @staticmethod
    def create(
        db: Session,
        utilisateur_id: int,
        valeur: str,
        type_jeton: TypeJeton,
        expire_le,
        utilise: bool = False,
    ) -> Token:
        jeton = Token(
            utilisateur_id=utilisateur_id,
            valeur=valeur,
            type_jeton=type_jeton,
            expire_le=expire_le,
            utilise=utilise,
        )
        db.add(jeton)
        db.commit()
        db.refresh(jeton)
        return jeton

    @staticmethod
    def get_by_valeur_et_type(db: Session, valeur: str, type_jeton: TypeJeton):
        return (
            db.query(Token)
            .filter(Token.valeur == valeur, Token.type_jeton == type_jeton)
            .first()
        )
