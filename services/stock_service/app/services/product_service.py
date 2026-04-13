from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..core.database import SessionLocal
from ..models.tables import Product


def get_all_products(q: str | None = None, limit: int = 100):
    db: Session = SessionLocal()
    try:
        query = db.query(Product)

        if q:
            search = f"%{q}%"
            query = query.filter(
                or_(
                    Product.nom.ilike(search),
                    Product.sku.ilike(search),
                    Product.marque.ilike(search),
                    Product.categorie.ilike(search),
                )
            )

        rows = query.limit(limit).all()

        return [
            {
                "id": p.id,
                "sku": p.sku,
                "nom": p.nom,
                "categorie": p.categorie,
                "marque": p.marque,
                "prixVente": p.prix_vente,
                "prixCout": p.prix_cout,
                "stockDisponible": p.stock_disponible,
                "stockReserve": p.stock_reserve,
                "seuilMin": p.seuil_min,
                "seuilMax": p.seuil_max,
                "statut": p.statut,
            }
            for p in rows
        ]
    finally:
        db.close()


def get_product_by_id_service(product_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(Product).filter(Product.id == product_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        return {
            "id": p.id,
            "sku": p.sku,
            "nom": p.nom,
            "categorie": p.categorie,
            "marque": p.marque,
            "description": p.description,
            "prixVente": p.prix_vente,
            "prixCout": p.prix_cout,
            "stockDisponible": p.stock_disponible,
            "stockReserve": p.stock_reserve,
            "stockMinimum": p.stock_minimum,
            "seuilMin": p.seuil_min,
            "seuilMax": p.seuil_max,
            "statut": p.statut,
        }
    finally:
        db.close()


def get_product_pricing_details_service(product_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(Product).filter(Product.id == product_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        return {
            "id": p.id,
            "sku": p.sku,
            "nom": p.nom,
            "prixVente": p.prix_vente,
            "prixCout": p.prix_cout,
            "margeReservee": p.marge_reservee,
            "categorie": p.categorie,
            "marque": p.marque,
        }
    finally:
        db.close()


def get_product_stock_details_service(product_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(Product).filter(Product.id == product_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Produit introuvable")

        return {
            "id": p.id,
            "sku": p.sku,
            "nom": p.nom,
            "stockDisponible": p.stock_disponible,
            "stockReserve": p.stock_reserve,
            "stockMinimum": p.stock_minimum,
            "seuilMin": p.seuil_min,
            "seuilMax": p.seuil_max,
            "statut": p.statut,
        }
    finally:
        db.close()