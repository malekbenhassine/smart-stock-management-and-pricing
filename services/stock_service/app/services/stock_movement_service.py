from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.tables import Product, StockMovement
from app.schemas.schemas import StockMovementCreate, StockMovementUpdate


MOVEMENT_TYPES = {
    "ENTREE",
    "SORTIE",
    "AJUSTEMENT_POSITIF",
    "AJUSTEMENT_NEGATIF",
    "RESERVATION",
    "ANNULATION_RESERVATION",
}

NEGATIVE_TYPES = {
    "SORTIE",
    "AJUSTEMENT_NEGATIF",
    "RESERVATION",
}

POSITIVE_TYPES = {
    "ENTREE",
    "AJUSTEMENT_POSITIF",
    "ANNULATION_RESERVATION",
}

DEMAND_SIGNAL_TYPES = {
    "SORTIE",
    "AJUSTEMENT_NEGATIF",
    "RESERVATION",
}


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _serialize_movement(
    movement: StockMovement,
    product_name: str | None = None,
    product_sku: str | None = None,
) -> dict:
    return {
        "id": movement.id,
        "produit_id": movement.produit_id,
        "product_name": product_name,
        "product_sku": product_sku,
        "type": movement.type,
        "quantite": movement.quantite,
        "dateMouvement": movement.date_mouvement,
        "justification": movement.justification,
    }


def _apply_stock_effect(
    product: Product,
    movement_type: str,
    qty: int,
    reverse: bool = False,
) -> None:
    if movement_type not in MOVEMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Type de mouvement invalide : {movement_type}",
        )

    if qty <= 0:
        raise HTTPException(
            status_code=400,
            detail="La quantité doit être strictement positive.",
        )

    stock_dispo = _safe_int(product.stock_disponible, 0)
    stock_reserve = _safe_int(product.stock_reserve, 0)

    sign = -1 if reverse else 1

    if movement_type == "ENTREE":
        stock_dispo += sign * qty

    elif movement_type == "SORTIE":
        stock_dispo -= sign * qty

    elif movement_type == "AJUSTEMENT_POSITIF":
        stock_dispo += sign * qty

    elif movement_type == "AJUSTEMENT_NEGATIF":
        stock_dispo -= sign * qty

    elif movement_type == "RESERVATION":
        stock_dispo -= sign * qty
        stock_reserve += sign * qty

    elif movement_type == "ANNULATION_RESERVATION":
        stock_dispo += sign * qty
        stock_reserve -= sign * qty

    if stock_dispo < 0:
        raise HTTPException(
            status_code=400,
            detail="Stock disponible insuffisant pour appliquer ce mouvement.",
        )

    if stock_reserve < 0:
        raise HTTPException(
            status_code=400,
            detail="Stock réservé insuffisant pour appliquer ce mouvement.",
        )

    product.stock_disponible = stock_dispo
    product.stock_reserve = stock_reserve


def record_stock_trace_only(
    db: Session,
    produit_id: int,
    movement_type: str,
    quantite: int,
    justification: str | None = None,
    date_mouvement: datetime | None = None,
) -> StockMovement | None:
    qty = _safe_int(quantite, 0)

    if qty <= 0:
        return None

    if movement_type not in MOVEMENT_TYPES:
        return None

    movement = StockMovement(
        produit_id=produit_id,
        type=movement_type,
        quantite=qty,
        date_mouvement=date_mouvement or datetime.utcnow(),
        justification=justification,
    )

    db.add(movement)
    return movement


def create_stock_movement_service(payload: StockMovementCreate, db: Session) -> dict:
    product = db.query(Product).filter(Product.id == payload.produit_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable.")

    movement = StockMovement(
        produit_id=payload.produit_id,
        type=payload.type,
        quantite=payload.quantite,
        date_mouvement=payload.dateMouvement or datetime.utcnow(),
        justification=payload.justification,
    )

    _apply_stock_effect(product, movement.type, movement.quantite, reverse=False)

    db.add(movement)
    db.commit()
    db.refresh(movement)
    db.refresh(product)

    return {
        "status": "success",
        "movement": _serialize_movement(
            movement,
            product_name=product.nom,
            product_sku=product.sku,
        ),
        "product": {
            "id": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "stockDisponible": product.stock_disponible,
            "stockReserve": product.stock_reserve,
        },
    }


def list_stock_movements_service(
    db: Session,
    produit_id: int | None = None,
    movement_type: str | None = None,
    limit: int = 100,
) -> dict:
    query = (
        db.query(
            StockMovement,
            Product.nom.label("product_name"),
            Product.sku.label("product_sku"),
        )
        .join(Product, Product.id == StockMovement.produit_id)
    )

    if produit_id is not None:
        query = query.filter(StockMovement.produit_id == produit_id)

    if movement_type:
        query = query.filter(StockMovement.type == movement_type)

    rows = (
        query
        .order_by(StockMovement.date_mouvement.desc(), StockMovement.id.desc())
        .limit(min(limit, 500))
        .all()
    )

    items = []

    for movement, product_name, product_sku in rows:
        items.append(
            _serialize_movement(
                movement,
                product_name=product_name,
                product_sku=product_sku,
            )
        )

    return {
        "status": "success",
        "total": len(items),
        "items": items,
    }


def update_stock_movement_service(
    movement_id: int,
    payload: StockMovementUpdate,
    db: Session,
) -> dict:
    movement = db.query(StockMovement).filter(StockMovement.id == movement_id).first()

    if not movement:
        raise HTTPException(status_code=404, detail="Mouvement introuvable.")

    product = db.query(Product).filter(Product.id == movement.produit_id).first()

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produit lié au mouvement introuvable.",
        )

    old_type = movement.type
    old_qty = _safe_int(movement.quantite, 0)

    new_type = payload.type or old_type
    new_qty = payload.quantite if payload.quantite is not None else old_qty

    _apply_stock_effect(product, old_type, old_qty, reverse=True)
    _apply_stock_effect(product, new_type, new_qty, reverse=False)

    movement.type = new_type
    movement.quantite = new_qty

    if payload.justification is not None:
        movement.justification = payload.justification

    if payload.dateMouvement is not None:
        movement.date_mouvement = payload.dateMouvement

    db.commit()
    db.refresh(movement)
    db.refresh(product)

    return {
        "status": "success",
        "movement": _serialize_movement(
            movement,
            product_name=product.nom,
            product_sku=product.sku,
        ),
        "product": {
            "id": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "stockDisponible": product.stock_disponible,
            "stockReserve": product.stock_reserve,
        },
    }


def get_product_stock_movement_summary_service(
    product_id: int,
    db: Session,
    days: int = 30,
) -> dict:
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable.")

    since = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.query(
            StockMovement.type,
            func.coalesce(func.sum(StockMovement.quantite), 0),
        )
        .filter(StockMovement.produit_id == product_id)
        .filter(StockMovement.date_mouvement >= since)
        .group_by(StockMovement.type)
        .all()
    )

    totals = {movement_type: int(total or 0) for movement_type, total in rows}

    entrees = (
        totals.get("ENTREE", 0)
        + totals.get("AJUSTEMENT_POSITIF", 0)
        + totals.get("ANNULATION_RESERVATION", 0)
    )

    sorties = (
        totals.get("SORTIE", 0)
        + totals.get("AJUSTEMENT_NEGATIF", 0)
        + totals.get("RESERVATION", 0)
    )

    avg_daily_output = sorties / days if days > 0 else 0

    return {
        "status": "success",
        "product": {
            "id": product.id,
            "sku": product.sku,
            "nom": product.nom,
            "stockDisponible": product.stock_disponible or 0,
            "stockReserve": product.stock_reserve or 0,
            "stockMinimum": product.stock_minimum,
            "seuilMin": product.seuil_min,
            "seuilMax": product.seuil_max,
        },
        "periodDays": days,
        "totalsByType": totals,
        "entrees": entrees,
        "sorties": sorties,
        "avgDailyOutput": round(avg_daily_output, 2),
        "demandSignal": sorties > 0,
    }


def estimate_demand_from_movements(
    product_id: int,
    db: Session,
    days: int = 30,
) -> dict:
    since = datetime.utcnow() - timedelta(days=days)

    total = (
        db.query(func.coalesce(func.sum(StockMovement.quantite), 0))
        .filter(StockMovement.produit_id == product_id)
        .filter(StockMovement.date_mouvement >= since)
        .filter(StockMovement.type.in_(list(DEMAND_SIGNAL_TYPES)))
        .scalar()
    )

    total = int(total or 0)
    avg_daily = total / days if days > 0 else 0

    return {
        "source": "mouvement_stock" if total > 0 else "none",
        "days": days,
        "total_output": total,
        "avg_daily_output": avg_daily,
        "weekly_forecast": avg_daily * 7,
    }