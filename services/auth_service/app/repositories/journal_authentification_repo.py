from typing import Optional

from sqlalchemy.orm import Session

from app.models.journal_authentification import JournalAuthentification


class JournalAuthentificationRepository:
    @staticmethod
    def creer(
        db: Session,
        type_evenement: str,
        statut: str,
        utilisateur_id: Optional[int] = None,
        adresse_email: Optional[str] = None,
        adresse_ip: Optional[str] = None,
        navigateur: Optional[str] = None,
        message: Optional[str] = None,
    ) -> JournalAuthentification:
        journal = JournalAuthentification(
            type_evenement=type_evenement,
            statut=statut,
            utilisateur_id=utilisateur_id,
            adresse_email=adresse_email,
            adresse_ip=adresse_ip,
            navigateur=navigateur,
            message=message,
        )
        db.add(journal)
        db.commit()
        db.refresh(journal)
        return journal

    @staticmethod
    def lister(db: Session, limite: int = 100):
        return (
            db.query(JournalAuthentification)
            .order_by(JournalAuthentification.cree_le.desc())
            .limit(limite)
            .all()
        )
