from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..models.tables import Supplier


def serialize_supplier(s: Supplier):
    return {
        "id": s.id,
        "nom": s.nom,
        "tel": s.tel,
        "adresse": s.adresse,
        "leadTimejours": s.lead_time_jours,
        "scorefiabilite": s.score_fiabilite,
    }


def get_all_suppliers_service(db: Session, q: str | None = None):
    query = db.query(Supplier)

    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Supplier.nom.ilike(search),
                Supplier.tel.ilike(search),
                Supplier.adresse.ilike(search),
            )
        )

    rows = query.order_by(Supplier.id.desc()).all()
    return [serialize_supplier(s) for s in rows]


def get_supplier_by_id_service(supplier_id: int, db: Session):
    obj = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")
    return serialize_supplier(obj)


def create_supplier_service(payload, db: Session):
    obj = Supplier(
        nom=payload.nom,
        tel=payload.tel,
        adresse=payload.adresse,
        lead_time_jours=payload.leadTimejours,
        score_fiabilite=payload.scorefiabilite,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return serialize_supplier(obj)


def update_supplier_service(supplier_id: int, payload, db: Session):
    obj = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    data = payload.model_dump(exclude_unset=True)

    mapping = {
        "nom": "nom",
        "tel": "tel",
        "adresse": "adresse",
        "leadTimejours": "lead_time_jours",
        "scorefiabilite": "score_fiabilite",
    }

    for key, value in data.items():
        setattr(obj, mapping[key], value)

    db.commit()
    db.refresh(obj)
    return serialize_supplier(obj)


def delete_supplier_service(supplier_id: int, db: Session):
    obj = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Fournisseur introuvable")

    db.delete(obj)
    db.commit()
    return {"message": "Fournisseur supprimé avec succès"}