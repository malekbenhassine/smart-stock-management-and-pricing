from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.tables import Supplier, SupplierOrder, SupplierOrderLine, Product


def serialize_order_line(line: SupplierOrderLine):
    return {
        "id": line.id,
        "commandeId": line.commande_id,
        "produitId": line.produit_id,
        "quantiteCommandee": line.quantite_commandee,
        "quantiteRecue": line.quantite_recue,
        "prixAchatUnitaire": line.prix_achat_unitaire,
    }


def serialize_order(order: SupplierOrder, lines: list[SupplierOrderLine] | None = None):
    data = {
        "id": order.id,
        "fournisseurId": order.fournisseur_id,
        "idCommande": order.id_commande,
        "dateCommande": order.date_commande,
        "dateReceptionPrevue": order.date_reception_prevue,
        "dateReceptionReelle": order.date_reception_reelle,
        "statut": order.statut,
    }

    if lines is not None:
        data["lignes"] = [serialize_order_line(line) for line in lines]

    return data


def get_all_supplier_orders_service(db: Session):
    rows = db.query(SupplierOrder).order_by(SupplierOrder.id.desc()).all()
    return [serialize_order(o) for o in rows]


def get_supplier_order_by_id_service(order_id: int, db: Session):
    order = db.query(SupplierOrder).filter(SupplierOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Commande fournisseur introuvable")

    lines = db.query(SupplierOrderLine).filter(SupplierOrderLine.commande_id == order.id).all()
    return serialize_order(order, lines)


def create_supplier_order_service(payload, db: Session):
    supplier = db.query(Supplier).filter(Supplier.id == payload.fournisseur_id).first()
    if not supplier:
        raise HTTPException(status_code=400, detail="Le fournisseur indiqué n'existe pas")

    existing = db.query(SupplierOrder).filter(SupplierOrder.id_commande == payload.idCommande).first()
    if existing:
        raise HTTPException(status_code=400, detail="Une commande avec cet identifiant existe déjà")

    obj = SupplierOrder(
        fournisseur_id=payload.fournisseur_id,
        id_commande=payload.idCommande,
        date_commande=payload.dateCommande,
        date_reception_prevue=payload.dateReceptionPrevue,
        date_reception_reelle=payload.dateReceptionReelle,
        statut=payload.statut,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return serialize_order(obj)


def update_supplier_order_service(order_id: int, payload, db: Session):
    obj = db.query(SupplierOrder).filter(SupplierOrder.id == order_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Commande fournisseur introuvable")

    data = payload.model_dump(exclude_unset=True)

    if "fournisseur_id" in data:
        supplier = db.query(Supplier).filter(Supplier.id == data["fournisseur_id"]).first()
        if not supplier:
            raise HTTPException(status_code=400, detail="Le fournisseur indiqué n'existe pas")

    if "idCommande" in data and data["idCommande"] != obj.id_commande:
        existing = db.query(SupplierOrder).filter(
            SupplierOrder.id_commande == data["idCommande"],
            SupplierOrder.id != order_id,
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Une autre commande utilise déjà cet identifiant")

    mapping = {
        "fournisseur_id": "fournisseur_id",
        "idCommande": "id_commande",
        "dateCommande": "date_commande",
        "dateReceptionPrevue": "date_reception_prevue",
        "dateReceptionReelle": "date_reception_reelle",
        "statut": "statut",
    }

    for key, value in data.items():
        setattr(obj, mapping[key], value)

    db.commit()
    db.refresh(obj)
    return serialize_order(obj)


def delete_supplier_order_service(order_id: int, db: Session):
    obj = db.query(SupplierOrder).filter(SupplierOrder.id == order_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Commande fournisseur introuvable")

    db.query(SupplierOrderLine).filter(SupplierOrderLine.commande_id == order_id).delete()
    db.delete(obj)
    db.commit()
    return {"message": "Commande fournisseur supprimée avec succès"}


def add_supplier_order_line_service(order_id: int, payload, db: Session):
    order = db.query(SupplierOrder).filter(SupplierOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Commande fournisseur introuvable")

    product = db.query(Product).filter(Product.id == payload.produit_id).first()
    if not product:
        raise HTTPException(status_code=400, detail="Le produit indiqué n'existe pas")

    obj = SupplierOrderLine(
        commande_id=order_id,
        produit_id=payload.produit_id,
        quantite_commandee=payload.quantiteCommandee,
        quantite_recue=payload.quantiteRecue,
        prix_achat_unitaire=payload.prixAchatUnitaire,
    )

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return serialize_order_line(obj)


def update_supplier_order_line_service(order_id: int, line_id: int, payload, db: Session):
    line = db.query(SupplierOrderLine).filter(
        SupplierOrderLine.id == line_id,
        SupplierOrderLine.commande_id == order_id,
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Ligne de commande introuvable")

    data = payload.model_dump(exclude_unset=True)

    if "produit_id" in data:
        product = db.query(Product).filter(Product.id == data["produit_id"]).first()
        if not product:
            raise HTTPException(status_code=400, detail="Le produit indiqué n'existe pas")

    mapping = {
        "produit_id": "produit_id",
        "quantiteCommandee": "quantite_commandee",
        "quantiteRecue": "quantite_recue",
        "prixAchatUnitaire": "prix_achat_unitaire",
    }

    for key, value in data.items():
        setattr(line, mapping[key], value)

    db.commit()
    db.refresh(line)
    return serialize_order_line(line)


def delete_supplier_order_line_service(order_id: int, line_id: int, db: Session):
    line = db.query(SupplierOrderLine).filter(
        SupplierOrderLine.id == line_id,
        SupplierOrderLine.commande_id == order_id,
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Ligne de commande introuvable")

    db.delete(line)
    db.commit()
    return {"message": "Ligne de commande supprimée avec succès"}