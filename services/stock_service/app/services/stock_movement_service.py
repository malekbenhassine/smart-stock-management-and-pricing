from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.services.manager_service import enregistrer_activite
from app.models.tables import Product, Sale, SaleLine, StockMovement
from app.schemas.schemas import StockMovementCreate, StockMovementUpdate
from app.services.alert_event_client import trigger_stock_alert_scan


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

# Seules les sorties réellement liées à une vente client doivent alimenter la demande.
# Les pertes, casses, corrections ou réservations ne sont pas des ventes.
SALE_JUSTIFICATION_CODES = {
    "VENTE_CLIENT",
    "VENTE_CLIENT_DIRECTE",
    "COMMANDE_CLIENT_LIVREE",
}

SALE_JUSTIFICATION_KEYWORDS = {
    "VENTE",
    "VENTE CLIENT",
    "CLIENT",
    "COMMANDE CLIENT",
}

DEMAND_SIGNAL_TYPES = {"SORTIE"}





def _normalize_text(value: str | None) -> str:
    return str(value or "").strip().upper().replace("É", "E").replace("È", "E").replace("Ê", "E")


def is_customer_sale_movement(movement_type: str | None, justification: str | None) -> bool:
    """
    Retourne True seulement si le mouvement doit être considéré comme une vente client.

    Règle métier :
    - type = SORTIE
    - justification = VENTE_CLIENT / VENTE_CLIENT_DIRECTE / COMMANDE_CLIENT_LIVREE
      ou ancien texte libre contenant une notion claire de vente client.
    """
    movement_type_normalized = _normalize_text(movement_type)
    justification_normalized = _normalize_text(justification)

    if movement_type_normalized != "SORTIE":
        return False

    if justification_normalized in SALE_JUSTIFICATION_CODES:
        return True

    return any(keyword in justification_normalized for keyword in SALE_JUSTIFICATION_KEYWORDS)


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
        # Utile côté front : permet d'afficher clairement si ce mouvement alimente la demande.
        "countsAsSale": is_customer_sale_movement(movement.type, movement.justification),
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



def _create_sale_from_customer_movement(
    db: Session,
    product: Product,
    movement: StockMovement,
) -> Sale | None:
    """
    Quand un mouvement de stock est une vraie vente client, on crée aussi
    une vente applicative dans ventes + lignes_ventes.

    Pourquoi ?
    - mouvement_stock garde la traçabilité stock ;
    - ventes/lignes_ventes représentent les ventes métier ;
    - les KPI, la prévision, le pricing et l'élimination peuvent ensuite
      retrouver cette vente comme une vraie vente applicative.

    Protection anti-doublon :
    cette fonction est appelée uniquement au moment de la création du mouvement.
    Les services KPI ignorent déjà les mouvements d'une date si une ligne de vente
    existe ce jour-là, donc on évite le double comptage.
    """
    if not is_customer_sale_movement(movement.type, movement.justification):
        return None

    sale = Sale(
        date_vente=movement.date_mouvement or datetime.utcnow(),
        source="mouvement_stock",
        statut="VALIDEE",
    )
    db.add(sale)
    db.flush()

    sale_line = SaleLine(
        vente_id=sale.id,
        produit_id=product.id,
        quantite=_safe_int(movement.quantite, 0),
        prix_vente_unitaire=product.prix_vente or 0,
    )
    db.add(sale_line)
    db.flush()

    return sale

def create_stock_movement_service(payload: StockMovementCreate, db: Session) -> dict:
    sale = None

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
    db.flush()

    sale = _create_sale_from_customer_movement(db=db, product=product, movement=movement)

    enregistrer_activite(
        db=db,
        role_utilisateur="RESPONSABLE_STOCK",
        nom_utilisateur="Responsable stock",
        type_action="MOUVEMENT_STOCK",
        type_entite="MOUVEMENT_STOCK",
        entite_id=movement.id,
        produit_id=product.id,
        description=f"Mouvement stock {movement.type} de {movement.quantite} unité(s) pour le produit : {product.nom}",
        donnees={
            "type": movement.type,
            "quantite": movement.quantite,
            "justification": movement.justification,
            "stockDisponibleApres": product.stock_disponible,
            "stockReserveApres": product.stock_reserve,
            "venteCreee": sale is not None,
        },
    )

    db.commit()
    db.refresh(movement)
    db.refresh(product)

    trigger_stock_alert_scan()

    return {
        "status": "success",
        "movement": _serialize_movement(movement, product_name=product.nom, product_sku=product.sku),
        "saleCreated": sale is not None,
        "sale": {"id": sale.id, "source": sale.source, "statut": sale.statut, "dateVente": sale.date_vente} if sale is not None else None,
        "product": {"id": product.id, "sku": product.sku, "nom": product.nom, "stockDisponible": product.stock_disponible, "stockReserve": product.stock_reserve},
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
            StockMovement.justification,
            func.coalesce(func.sum(StockMovement.quantite), 0),
        )
        .filter(StockMovement.produit_id == product_id)
        .filter(StockMovement.date_mouvement >= since)
        .group_by(StockMovement.type, StockMovement.justification)
        .all()
    )

    totals: dict[str, int] = {}
    totals_by_justification: dict[str, int] = {}
    customer_sales_output = 0

    for movement_type, justification, total in rows:
        qty = int(total or 0)
        totals[movement_type] = totals.get(movement_type, 0) + qty

        justification_key = justification or "NON_RENSEIGNEE"
        totals_by_justification[justification_key] = (
            totals_by_justification.get(justification_key, 0) + qty
        )

        if is_customer_sale_movement(movement_type, justification):
            customer_sales_output += qty

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

    technical_outputs = max(sorties - customer_sales_output, 0)
    avg_daily_output = customer_sales_output / days if days > 0 else 0

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
        "totalsByJustification": totals_by_justification,
        "entrees": entrees,
        "sorties": sorties,
        "ventesClientSorties": customer_sales_output,
        "sortiesTechniques": technical_outputs,
        "avgDailyOutput": round(avg_daily_output, 2),
        "weeklyForecastFromSalesMovements": round(avg_daily_output * 7, 2),
        "demandSignal": customer_sales_output > 0,
        "demandSource": "mouvement_stock_vente_client" if customer_sales_output > 0 else "none",
    }


def estimate_demand_from_movements(
    product_id: int,
    db: Session,
    days: int = 30,
) -> dict:
    since = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.query(StockMovement.type, StockMovement.justification, StockMovement.quantite)
        .filter(StockMovement.produit_id == product_id)
        .filter(StockMovement.date_mouvement >= since)
        .filter(StockMovement.type.in_(list(DEMAND_SIGNAL_TYPES)))
        .all()
    )

    total = sum(
        _safe_int(row.quantite, 0)
        for row in rows
        if is_customer_sale_movement(row.type, row.justification)
    )

    avg_daily = total / days if days > 0 else 0

    return {
        "source": "mouvement_stock_vente_client" if total > 0 else "none",
        "days": days,
        "total_output": total,
        "avg_daily_output": avg_daily,
        "weekly_forecast": avg_daily * 7,
        "rule": "Seules les sorties avec justification VENTE_CLIENT sont considérées comme ventes.",
    }
