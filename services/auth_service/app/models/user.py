from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.role import UserRole


class User(Base):
    __tablename__ = "utilisateur"

    id = Column(Integer, primary_key=True, index=True)

    prenom = Column(String(100), nullable=False)
    nom = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    mot_de_passe_hash = Column(String(255), nullable=True)

    roles = Column(JSON, nullable=False, default=list)

    telephone = Column(String(30), nullable=True)
    adresse = Column(String(255), nullable=True)
    date_naissance = Column(Date, nullable=True)

    est_actif = Column(Boolean, default=False, nullable=False)
    email_verifie = Column(Boolean, default=False, nullable=False)
    doit_changer_mot_de_passe = Column(Boolean, default=False, nullable=False)

    cree_le = Column(DateTime, default=datetime.utcnow, nullable=False)
    modifie_le = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    mot_de_passe_modifie_le = Column("password_updated_at", DateTime, nullable=True)

    jetons = relationship("Token", back_populates="utilisateur", cascade="all, delete-orphan")
    journaux_authentification = relationship("JournalAuthentification", back_populates="utilisateur")

    @property
    def nom_affichage(self) -> str:
        return f"{self.prenom or ''} {self.nom or ''}".strip()

    def has_role(self, role: UserRole | str) -> bool:
        role_value = role.value if isinstance(role, UserRole) else str(role)
        return role_value in (self.roles or [])






    @property
    def nom_complet(self) -> str:
        return self.nom_affichage

    @nom_complet.setter
    def nom_complet(self, value: str) -> None:
        value = (value or "").strip()
        parties = value.split()
        if len(parties) <= 1:
            self.prenom = value
            self.nom = ""
        else:
            self.prenom = parties[0]
            self.nom = " ".join(parties[1:])

    @property
    def role(self):
        if not self.roles:
            return None
        return self.roles[0]

    @role.setter
    def role(self, value):
        if value is None:
            self.roles = []
        elif isinstance(value, UserRole):
            self.roles = [value.value]
        else:
            self.roles = [str(value)]

    @property
    def password_updated_at(self):
        return self.mot_de_passe_modifie_le

    @password_updated_at.setter
    def password_updated_at(self, value):
        self.mot_de_passe_modifie_le = value
