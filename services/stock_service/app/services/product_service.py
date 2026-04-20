from statistics import median
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..models.tables import Product, ProductCompetitor


def serialize_product(p: Product):
    return {
        "id": p.id,
        "sku": p.sku,
        "nom": p.nom,
        "categorie": p.categorie,
        "marque": p.marque,
        "description": p.description,
        "prixVente": p.prix_vente,
        "prixCout": p.prix_cout,
        "margeReservee": p.marge_reservee,
        "stockDisponible": p.stock_disponible,
        "stockReserve": p.stock_reserve,
        "stockMinimum": p.stock_minimum,
        "seuilMin": p.seuil_min,
        "seuilMax": p.seuil_max,
        "statut": p.statut,
        "dateDebutObservation": p.date_debut_observation,
        "dateFinObservation": p.date_fin_observation,
    }


def get_all_products(db: Session, q: str | None = None):
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

    rows = query.order_by(Product.id.desc()).all()
    return [serialize_product(p) for p in rows]


def get_product_by_id_service(product_id: int, db: Session):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return serialize_product(p)


def get_product_pricing_details_service(product_id: int, db: Session):
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


def get_product_stock_details_service(product_id: int, db: Session):
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


def create_product_service(payload, db: Session):
    existing = db.query(Product).filter(Product.sku == payload.sku).first()
    if existing:
        raise HTTPException(status_code=400, detail="Un produit avec ce SKU existe déjà")

    obj = Product(
        sku=payload.sku,
        nom=payload.nom,
        categorie=payload.categorie,
        marque=payload.marque,
        description=payload.description,
        prix_cout=payload.prixCout,
        prix_vente=payload.prixVente,
        marge_reservee=payload.margeReservee,
        stock_disponible=payload.stockDisponible,
        stock_reserve=payload.stockReserve,
        stock_minimum=payload.stockMinimum,
        seuil_max=payload.seuilMax,
        seuil_min=payload.seuilMin,
        statut=payload.statut,
        date_debut_observation=payload.dateDebutObservation,
        date_fin_observation=payload.dateFinObservation,
    )

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return serialize_product(obj)


def update_product_service(product_id: int, payload, db: Session):
    obj = db.query(Product).filter(Product.id == product_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    data = payload.model_dump(exclude_unset=True)

    if "sku" in data and data["sku"] != obj.sku:
        existing = db.query(Product).filter(Product.sku == data["sku"], Product.id != product_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Un autre produit utilise déjà ce SKU")

    mapping = {
        "sku": "sku",
        "nom": "nom",
        "categorie": "categorie",
        "marque": "marque",
        "description": "description",
        "prixCout": "prix_cout",
        "prixVente": "prix_vente",
        "margeReservee": "marge_reservee",
        "stockDisponible": "stock_disponible",
        "stockReserve": "stock_reserve",
        "stockMinimum": "stock_minimum",
        "seuilMax": "seuil_max",
        "seuilMin": "seuil_min",
        "statut": "statut",
        "dateDebutObservation": "date_debut_observation",
        "dateFinObservation": "date_fin_observation",
    }

    for key, value in data.items():
        setattr(obj, mapping[key], value)

    db.commit()
    db.refresh(obj)
    return serialize_product(obj)


def delete_product_service(product_id: int, db: Session):
    obj = db.query(Product).filter(Product.id == product_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    db.delete(obj)
    db.commit()
    return {"message": "Produit supprimé avec succès"}


def calculate_initial_price_recommendation_service(product_id: int, db: Session):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    competitors = (
        db.query(ProductCompetitor)
        .filter(
            ProductCompetitor.produit_id == product_id,
            ProductCompetitor.fiable.is_(True),
            ProductCompetitor.prix_concurrent.isnot(None),
        )
        .all()
    )

    prices = []
    for c in competitors:
        if c.prix_concurrent is not None and c.prix_concurrent > 0:
            prices.append(c.prix_concurrent)

    competitor_count = len(prices)

    if competitor_count >= 3:
        recommended = round(median(prices), 2)
        return {
            "productId": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "currentPrixVente": product.prix_vente,
            "recommendedPrixVente": recommended,
            "source": "CONCURRENT",
            "competitorCount": competitor_count,
            "message": "Recommandation calculée uniquement, non appliquée.",
        }

    if product.prix_cout is not None and product.prix_cout > 0:
        margin_rate = 0.20
        recommended = round(product.prix_cout * (1 + margin_rate), 2)
        return {
            "productId": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "currentPrixVente": product.prix_vente,
            "recommendedPrixVente": recommended,
            "source": "COST_PLUS_MARGIN",
            "competitorCount": competitor_count,
            "message": "Recommandation calculée uniquement, non appliquée.",
        }

    return {
        "productId": product.id,
        "sku": product.sku,
        "nom": product.nom,
        "currentPrixVente": product.prix_vente,
        "recommendedPrixVente": None,
        "source": "INSUFFICIENT_DATA",
        "competitorCount": competitor_count,
        "message": "Impossible de calculer une recommandation fiable.",
    }


def update_product_price_service(product_id: int, new_price: float, justification: str | None, db: Session):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")

    if new_price is None or new_price < 0:
        raise HTTPException(status_code=400, detail="Le nouveau prix doit être supérieur ou égal à 0")

    old_price = product.prix_vente

    if old_price is None:
        product.prix_vente = new_price
        db.commit()
        db.refresh(product)
        return {
            "message": "Prix mis à jour avec succès",
            "product": serialize_product(product),
            "oldPrixVente": old_price,
            "newPrixVente": new_price,
            "variationPercent": None,
            "justificationRequired": False,
            "justificationProvided": bool(justification),
        }

    if old_price == 0:
        variation_percent = 100.0 if new_price != 0 else 0.0
    else:
        variation_percent = abs((new_price - old_price) / old_price) * 100

    justification_required = variation_percent >= 50

    if justification_required and (justification is None or not justification.strip()):
        raise HTTPException(
            status_code=400,
            detail="Une justification est obligatoire lorsque la variation du prix est supérieure ou égale à 50%",
        )

    product.prix_vente = new_price
    db.commit()
    db.refresh(product)

    return {
        "message": "Prix mis à jour avec succès",
        "product": serialize_product(product),
        "oldPrixVente": old_price,
        "newPrixVente": new_price,
        "variationPercent": round(variation_percent, 2),
        "justificationRequired": justification_required,
        "justificationProvided": bool(justification and justification.strip()),
        "justification": justification.strip() if justification else None,
    }