from sqlalchemy.orm import Session

from app.models.password_reset_token import PasswordResetToken


class PasswordResetTokenRepository:
    @staticmethod
    def create(db: Session, **kwargs):
        reset_token = PasswordResetToken(**kwargs)
        db.add(reset_token)
        db.commit()
        db.refresh(reset_token)
        return reset_token

    @staticmethod
    def get_by_token(db: Session, token: str):
        return (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.token == token)
            .first()
        )