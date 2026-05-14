from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.tables import (
    DemandeModificationPrix,
    JournalActivite,
    Product,
    Sale,
    SaleLine,
)


def _round(value):
    if value is None:
        return None
    return round(float(value), 2)


def enregistrer_activite(
    db: Session,
    *,
    role_utilisateur: str,
    type_action: str,
    description: str,
    type_entite: str | None = None,
    entite_id: int | None = None,
    produit_id: int | None = None,
    nom_utilisateur: str | None = None,
    donnees: dict[str, Any] | None = None,
    commit: bool = False,
):
    ligne = JournalActivite(
        role_utilisateur=role_utilisateur,
        nom_utilisateur=nom_utilisateur,
        type_action=type_action,
        type_entite=type_entite,
        entite_id=entite_id,
        produit_id=produit_id,
        description=description,
        donnees=donnees or {},
    )
    db.add(ligne)
    if commit:
        db.commit()
        db.refresh(ligne)
    return ligne


def serializer_demande(demande: DemandeModificationPrix) -> dict:
    produit = demande.produit
    return {
        "id": demande.id,
        "produitId": demande.produit_id,
        "produitNom": produit.nom if produit else None,
        "produitSku": produit.sku if produit else None,
        "ancienPrix": _round(demande.ancien_prix),
        "nouveauPrix": _round(demande.nouveau_prix),
        "variationPourcentage": _round(demande.variation_pourcentage),
        "justification": demande.justification,
        "sourceRecommandation": demande.source_recommandation,
        "strategie": demande.strategie,
        "statut": demande.statut,
        "demandePar": demande.demande_par,
        "dateDemande": demande.date_demande,
        "validePar": demande.valide_par,
        "dateValidation": demande.date_validation,
        "commentaireManager": demande.commentaire_manager,
    }


def lister_demandes_modification_prix_service(
    db: Session,
    statut: str | None = "EN_ATTENTE_MANAGER",
    limit: int = 100,
) -> dict:
    query = db.query(DemandeModificationPrix).order_by(DemandeModificationPrix.id.desc())
    if statut:
        query = query.filter(DemandeModificationPrix.statut == statut)
    rows = query.limit(limit).all()
    return {"status": "success", "total": len(rows), "items": [serializer_demande(r) for r in rows]}


def valider_demande_modification_prix_service(
    db: Session,
    demande_id: int,
    commentaire_manager: str | None = None,
    nom_manager: str | None = "MANAGER",
) -> dict:
    demande = db.query(DemandeModificationPrix).filter(DemandeModificationPrix.id == demande_id).first()
    if not demande:
        raise HTTPException(status_code=404, detail="Demande de modification de prix introuvable")
    if demande.statut != "EN_ATTENTE_MANAGER":
        raise HTTPException(status_code=400, detail=f"Demande déjà traitée : {demande.statut}")

    produit = db.query(Product).filter(Product.id == demande.produit_id).first()
    if not produit:
        raise HTTPException(status_code=404, detail="Produit associé introuvable")

    produit.prix_vente = demande.nouveau_prix
    produit.statut_prix = "PRIX_VALIDE"
    produit.date_validation_prix = datetime.utcnow()
    produit.note_validation_prix = demande.justification

    demande.statut = "VALIDEE_MANAGER"
    demande.valide_par = nom_manager
    demande.date_validation = datetime.utcnow()
    demande.commentaire_manager = commentaire_manager

    enregistrer_activite(
        db,
        role_utilisateur="MANAGER",
        nom_utilisateur=nom_manager,
        type_action="VALIDATION_MODIFICATION_PRIX",
        type_entite="DEMANDE_MODIFICATION_PRIX",
        entite_id=demande.id,
        produit_id=produit.id,
        description=f"Le manager a validé le passage du prix de {demande.ancien_prix} à {demande.nouveau_prix} pour le produit {produit.nom}.",
        donnees={
            "ancienPrix": demande.ancien_prix,
            "nouveauPrix": demande.nouveau_prix,
            "variationPourcentage": demande.variation_pourcentage,
            "commentaireManager": commentaire_manager,
        },
    )

    db.commit()
    db.refresh(demande)
    db.refresh(produit)

    return {
        "status": "VALIDEE_MANAGER",
        "message": "Modification de prix validée par le manager.",
        "demande": serializer_demande(demande),
        "produit": {"id": produit.id, "nom": produit.nom, "prixVente": produit.prix_vente},
    }


def refuser_demande_modification_prix_service(
    db: Session,
    demande_id: int,
    commentaire_manager: str | None = None,
    nom_manager: str | None = "MANAGER",
) -> dict:
    demande = db.query(DemandeModificationPrix).filter(DemandeModificationPrix.id == demande_id).first()
    if not demande:
        raise HTTPException(status_code=404, detail="Demande de modification de prix introuvable")
    if demande.statut != "EN_ATTENTE_MANAGER":
        raise HTTPException(status_code=400, detail=f"Demande déjà traitée : {demande.statut}")

    produit = db.query(Product).filter(Product.id == demande.produit_id).first()

    demande.statut = "REFUSEE_MANAGER"
    demande.valide_par = nom_manager
    demande.date_validation = datetime.utcnow()
    demande.commentaire_manager = commentaire_manager

    enregistrer_activite(
        db,
        role_utilisateur="MANAGER",
        nom_utilisateur=nom_manager,
        type_action="REFUS_MODIFICATION_PRIX",
        type_entite="DEMANDE_MODIFICATION_PRIX",
        entite_id=demande.id,
        produit_id=demande.produit_id,
        description=f"Le manager a refusé la modification de prix demandée pour {produit.nom if produit else 'le produit'}.",
        donnees={
            "ancienPrix": demande.ancien_prix,
            "nouveauPrix": demande.nouveau_prix,
            "variationPourcentage": demande.variation_pourcentage,
            "commentaireManager": commentaire_manager,
        },
    )

    db.commit()
    db.refresh(demande)

    return {
        "status": "REFUSEE_MANAGER",
        "message": "Modification de prix refusée par le manager. Le prix actuel du produit n'a pas changé.",
        "demande": serializer_demande(demande),
    }


def lister_ventes_manager_service(db: Session, limit: int = 100) -> dict:
    ventes = db.query(Sale).order_by(Sale.id.desc()).limit(limit).all()
    items = []
    for vente in ventes:
        lignes = db.query(SaleLine, Product).outerjoin(Product, Product.id == SaleLine.produit_id).filter(SaleLine.vente_id == vente.id).all()
        total = sum(float(ligne.prix_vente_unitaire or 0) * int(ligne.quantite or 0) for ligne, _ in lignes)
        items.append({
            "id": vente.id,
            "dateVente": vente.date_vente,
            "source": vente.source,
            "statut": vente.statut,
            "total": _round(total),
            "nombreLignes": len(lignes),
            "lignes": [
                {
                    "id": ligne.id,
                    "produitId": ligne.produit_id,
                    "produitNom": produit.nom if produit else None,
                    "produitSku": produit.sku if produit else None,
                    "quantite": ligne.quantite,
                    "prixVenteUnitaire": _round(ligne.prix_vente_unitaire),
                    "totalLigne": _round(float(ligne.prix_vente_unitaire or 0) * int(ligne.quantite or 0)),
                }
                for ligne, produit in lignes
            ],
        })
    return {"status": "success", "total": len(items), "items": items}


def lister_journal_activites_service(
    db: Session,
    role: str | None = None,
    limit: int = 100,
) -> dict:
    query = db.query(JournalActivite).order_by(JournalActivite.id.desc())
    if role:
        query = query.filter(JournalActivite.role_utilisateur == role.upper())
    rows = query.limit(limit).all()
    return {
        "status": "success",
        "total": len(rows),
        "items": [
            {
                "id": r.id,
                "roleUtilisateur": r.role_utilisateur,
                "nomUtilisateur": r.nom_utilisateur,
                "typeAction": r.type_action,
                "typeEntite": r.type_entite,
                "entiteId": r.entite_id,
                "produitId": r.produit_id,
                "description": r.description,
                "donnees": r.donnees,
                "dateAction": r.date_action,
            }
            for r in rows
        ],
    }
