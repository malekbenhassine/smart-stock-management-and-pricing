from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.role import UserRole


class User(Base):
    __tablename__ = "utilisateur"

    id = Column(Integer, primary_key=True, index=True)

    # On garde prenom + nom seulement. Pas de nom_complet pour éviter la redondance.
    prenom = Column(String(100), nullable=False)
    nom = Column(String(100), nullable=False)

    email = Column(String(255), unique=True, index=True, nullable=False)
    mot_de_passe_hash = Column(String(255), nullable=True)

    # Un utilisateur peut avoir plusieurs rôles.
    # Exemple: ["STOCK_MANAGER", "PRICING_MANAGER"]
    roles = Column(JSON, nullable=False, default=list)

    telephone = Column(String(30), nullable=True)
    adresse = Column(String(255), nullable=True)
    date_naissance = Column(Date, nullable=True)

    est_actif = Column(Boolean, default=False, nullable=False)
    email_verifie = Column(Boolean, default=False, nullable=False)
    doit_changer_mot_de_passe = Column(Boolean, default=False, nullable=False)

    cree_le = Column(DateTime, default=datetime.utcnow, nullable=False)
    modifie_le = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    jetons = relationship("Token", back_populates="utilisateur", cascade="all, delete-orphan")

    @property
    def nom_affichage(self) -> str:
        return f"{self.prenom or ''} {self.nom or ''}".strip()

    def has_role(self, role: UserRole | str) -> bool:
        role_value = role.value if isinstance(role, UserRole) else str(role)
        return role_value in (self.roles or [])

    # Alias pour ne pas casser les anciens endroits qui lisaient nom_complet.
    @property
    def nom_complet(self):
        return self.nom_affichage

    @nom_complet.setter
    def nom_complet(self, value):
        value = (value or "").strip()
        parts = value.split()
        if len(parts) <= 1:
            self.prenom = value
            self.nom = ""
        else:
            self.prenom = parts[0]
            self.nom = " ".join(parts[1:])

    # Alias pour éviter de casser brutalement un ancien code qui utilise role.
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
    def full_name(self):
        return self.nom_affichage

    @full_name.setter
    def full_name(self, value):
        self.nom_complet = value

    @property
    def first_name(self):
        return self.prenom

    @first_name.setter
    def first_name(self, value):
        self.prenom = value

    @property
    def last_name(self):
        return self.nom

    @last_name.setter
    def last_name(self, value):
        self.nom = value

    @property
    def password_hash(self):
        return self.mot_de_passe_hash

    @password_hash.setter
    def password_hash(self, value):
        self.mot_de_passe_hash = value

    @property
    def phone(self):
        return self.telephone

    @phone.setter
    def phone(self, value):
        self.telephone = value

    @property
    def birth_date(self):
        return self.date_naissance

    @birth_date.setter
    def birth_date(self, value):
        self.date_naissance = value

    @property
    def is_active(self):
        return self.est_actif

    @is_active.setter
    def is_active(self, value):
        self.est_actif = value

    @property
    def email_verified(self):
        return self.email_verifie

    @email_verified.setter
    def email_verified(self, value):
        self.email_verifie = value
