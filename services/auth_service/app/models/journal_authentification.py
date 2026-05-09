from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class JournalAuthentification(Base):
    __tablename__ = "journal_authentification"

    id = Column(Integer, primary_key=True, index=True)

    type_evenement = Column(String(80), nullable=False, index=True)
    statut = Column(String(30), nullable=False, index=True)

    utilisateur_id = Column(Integer, ForeignKey("utilisateur.id", ondelete="SET NULL"), nullable=True, index=True)
    adresse_email = Column(String(255), nullable=True, index=True)

    adresse_ip = Column(String(80), nullable=True)
    navigateur = Column(Text, nullable=True)
    message = Column(Text, nullable=True)

    cree_le = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    utilisateur = relationship("User", lazy="joined")
