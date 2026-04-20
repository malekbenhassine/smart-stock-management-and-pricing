from sqlalchemy.orm import Session

from app.models.activation_token import ActivationToken


class TokenRepository:
    @staticmethod
    def create(db: Session, **kwargs):
        token = ActivationToken(**kwargs)
        db.add(token)
        db.commit()
        db.refresh(token)
        return token

    @staticmethod
    def get_by_token(db: Session, token: str):
        return db.query(ActivationToken).filter(ActivationToken.token == token).first()