from datetime import datetime
import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class TypeJeton(str, enum.Enum):
    ACTIVATION = "ACTIVATION"
    REINITIALISATION_MOT_DE_PASSE = "REINITIALISATION_MOT_DE_PASSE"


class Token(Base):
    __tablename__ = "jeton"

    id = Column(Integer, primary_key=True, index=True)
    utilisateur_id = Column(Integer, ForeignKey("utilisateur.id", ondelete="CASCADE"), nullable=False, index=True)
    valeur = Column(String(255), unique=True, index=True, nullable=False)
    type_jeton = Column(Enum(TypeJeton), nullable=False, index=True)
    expire_le = Column(DateTime, nullable=False)
    utilise = Column(Boolean, default=False, nullable=False)
    cree_le = Column(DateTime, default=datetime.utcnow, nullable=False)

    utilisateur = relationship("User", back_populates="jetons")

    @property
    def user_id(self):
        return self.utilisateur_id

    @user_id.setter
    def user_id(self, value):
        self.utilisateur_id = value

    @property
    def token(self):
        return self.valeur

    @token.setter
    def token(self, value):
        self.valeur = value

    @property
    def expires_at(self):
        return self.expire_le

    @expires_at.setter
    def expires_at(self, value):
        self.expire_le = value

    @property
    def used(self):
        return self.utilise

    @used.setter
    def used(self, value):
        self.utilise = value
