from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.manager_service import (
    enregistrer_activite,
    lister_demandes_modification_prix_service,
    lister_journal_activites_service,
    lister_ventes_manager_service,
    refuser_demande_modification_prix_service,
    valider_demande_modification_prix_service,
)

router = APIRouter(prefix="/manager", tags=["manager"])


@router.get("/demandes-modification-prix")
def lister_demandes_modification_prix(
    statut: str | None = Query(default="EN_ATTENTE_MANAGER"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return lister_demandes_modification_prix_service(db=db, statut=statut, limit=limit)


@router.post("/demandes-modification-prix/{demande_id}/valider")
def valider_demande_modification_prix(
    demande_id: int,
    commentaireManager: str | None = Body(default=None, embed=True),
    nomManager: str | None = Body(default="MANAGER", embed=True),
    db: Session = Depends(get_db),
):
    return valider_demande_modification_prix_service(
        db=db,
        demande_id=demande_id,
        commentaire_manager=commentaireManager,
        nom_manager=nomManager,
    )


@router.post("/demandes-modification-prix/{demande_id}/refuser")
def refuser_demande_modification_prix(
    demande_id: int,
    commentaireManager: str | None = Body(default=None, embed=True),
    nomManager: str | None = Body(default="MANAGER", embed=True),
    db: Session = Depends(get_db),
):
    return refuser_demande_modification_prix_service(
        db=db,
        demande_id=demande_id,
        commentaire_manager=commentaireManager,
        nom_manager=nomManager,
    )


@router.get("/ventes")
def lister_ventes_manager(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return lister_ventes_manager_service(db=db, limit=limit)


@router.get("/journal-activites")
def lister_journal_activites(
    role: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return lister_journal_activites_service(db=db, role=role, limit=limit)

@router.post("/journal-activites/import-csv")
def enregistrer_import_csv_activite(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    filename = payload.get("filename")
    table_name = payload.get("table")
    rows_imported = payload.get("rows_imported", 0)

    enregistrer_activite(
        db=db,
        role_utilisateur="RESPONSABLE_STOCK",
        nom_utilisateur="Responsable stock",
        type_action="IMPORT_DONNEES_CSV",
        type_entite="IMPORT_CSV",
        entite_id=None,
        produit_id=None,
        description=f"Import CSV terminé : {rows_imported} ligne(s) importée(s) dans {table_name}.",
        donnees={
            "filename": filename,
            "table": table_name,
            "rows_imported": rows_imported,
            "source": "csv_import_service",
        },
    )

    db.commit()

    return {
        "status": "success",
        "message": "Activité import CSV enregistrée.",
    }