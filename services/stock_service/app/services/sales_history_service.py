from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from ..models.tables import SalesHistory, Product, Sale, SaleLine, StockMovement


def bulk_upsert_sales_history(items, db: Session):
    """
    Import rapide de sales_history.

    Correction :
    - avant : SELECT ligne par ligne puis INSERT/UPDATE
    - maintenant : bulk upsert PostgreSQL
    - évite la saturation PostgreSQL pendant l'import des gros CSV
    """

    if not items:
        return {
            "status": "success",
            "message": "Aucune ligne à importer.",
            "rows": 0,
        }

    rows = []

    for item in items:
        rows.append(
            {
                "date": item.date,
                "store_id": item.store_id,
                "product_id": item.product_id,
                "category": item.category,
                "region": item.region,
                "sales": item.units_sold,
                "price": item.price,
                "stock": item.inventory_level,
                "discount": item.discount,
                "competitor_pricing": item.competitor_pricing,
                "units_ordered": item.units_ordered,
                "weather_condition": item.weather_condition,
                "holiday_promotion": item.holiday_promotion,
                "seasonality": item.seasonality,
            }
        )

    stmt = insert(SalesHistory).values(rows)

    stmt = stmt.on_conflict_do_update(
        index_elements=["date", "store_id", "product_id"],
        set_={
            "category": stmt.excluded.category,
            "region": stmt.excluded.region,
            "sales": stmt.excluded.sales,
            "price": stmt.excluded.price,
            "stock": stmt.excluded.stock,
            "discount": stmt.excluded.discount,
            "competitor_pricing": stmt.excluded.competitor_pricing,
            "units_ordered": stmt.excluded.units_ordered,
            "weather_condition": stmt.excluded.weather_condition,
            "holiday_promotion": stmt.excluded.holiday_promotion,
            "seasonality": stmt.excluded.seasonality,
        },
    )

    db.execute(stmt)
    db.commit()

    return {
        "status": "success",
        "message": "Sales history importé avec succès.",
        "rows": len(rows),
    }


def fetch_sales_history(
    db: Session,
    product_id: Optional[str] = None,
    store_id: Optional[str] = None,
    category: Optional[str] = None,
    region: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 1000,
):
    """
    Récupère l'historique des ventes avec filtres optionnels.

    Cette fonction est utilisée par les routes API.
    Il ne faut pas la supprimer.
    """

    query = db.query(SalesHistory)

    if product_id:
        query = query.filter(SalesHistory.product_id == product_id)

    if store_id:
        query = query.filter(SalesHistory.store_id == store_id)

    if category:
        query = query.filter(SalesHistory.category == category)

    if region:
        query = query.filter(SalesHistory.region == region)

    if start_date:
        query = query.filter(SalesHistory.date >= start_date)

    if end_date:
        query = query.filter(SalesHistory.date <= end_date)

    return (
        query.order_by(SalesHistory.date.desc())
        .limit(limit)
        .all()
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _resolve_product(db: Session, product_id: str | int | None) -> Product | None:
    """
    Résout un produit à partir :
    - soit de son SKU : ex. maxbook15972
    - soit de son ID numérique : ex. 302

    Cette résolution est indispensable parce que :
    - historique_ventes utilise le SKU dans SalesHistory.product_id ;
    - lignes_ventes et mouvement_stock utilisent l'ID numérique du produit.
    """
    raw = str(product_id or "").strip()
    if not raw:
        return None

    product = db.query(Product).filter(Product.sku == raw).first()
    if product:
        return product

    if raw.isdigit():
        return db.query(Product).filter(Product.id == int(raw)).first()

    return None


def fetch_recent_product_history(
    product_id: str,
    db: Session,
    days: int = 30,
    limit: int = 1000,
):
    """
    Historique récent utilisé par inference_service.

    ANCIENNE LOGIQUE :
    - lisait seulement historique_ventes / SalesHistory.
    - si le CSV ML n'était pas importé, le système voyait 0 jour d'historique.

    NOUVELLE LOGIQUE :
    - lit historique_ventes par SKU ;
    - ajoute les vraies ventes depuis ventes + lignes_ventes par produit_id ;
    - ajoute les mouvements de stock seulement si : SORTIE + VENTE_CLIENT
      ou SORTIE + COMMANDE_CLIENT_LIVREE.

    Résultat : un produit qui a des ventes réelles dans l'application ne reste plus
    bloqué en cold start à cause d'une table historique_ventes vide.
    """
    if not product_id:
        return []

    product = _resolve_product(db, product_id)
    raw_product_id = str(product_id).strip()

    sku = product.sku if product else raw_product_id
    numeric_product_id = None

    if product:
        numeric_product_id = product.id
    elif raw_product_id.isdigit():
        numeric_product_id = int(raw_product_id)

    candidate_dates: list[date] = []

    # 1. Date la plus récente dans historique_ventes.
    max_history_date = (
        db.query(func.max(SalesHistory.date))
        .filter(SalesHistory.product_id == sku)
        .scalar()
    )
    if max_history_date:
        candidate_dates.append(max_history_date)

    # 2. Date la plus récente dans ventes/lignes_ventes.
    if numeric_product_id is not None:
        max_sale_date = (
            db.query(func.max(func.date(Sale.date_vente)))
            .join(SaleLine, SaleLine.vente_id == Sale.id)
            .filter(SaleLine.produit_id == numeric_product_id)
            .scalar()
        )
        if max_sale_date:
            candidate_dates.append(max_sale_date)

        # 3. Date la plus récente dans mouvement_stock vente client.
        max_movement_date = (
            db.query(func.max(func.date(StockMovement.date_mouvement)))
            .filter(StockMovement.produit_id == numeric_product_id)
            .filter(func.upper(StockMovement.type) == "SORTIE")
            .filter(
                func.upper(StockMovement.justification).in_(
                    ["VENTE_CLIENT", "VENTE_CLIENT_DIRECTE", "COMMANDE_CLIENT_LIVREE"]
                )
            )
            .scalar()
        )
        if max_movement_date:
            candidate_dates.append(max_movement_date)

    if not candidate_dates:
        return []

    last_date = max(candidate_dates)
    start_date = last_date - timedelta(days=days)

    rows_by_date: dict[date, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Source 1 : historique_ventes / SalesHistory, utilisé par le CSV ML.
    # ------------------------------------------------------------------
    history_rows = (
        db.query(SalesHistory)
        .filter(SalesHistory.product_id == sku)
        .filter(SalesHistory.date >= start_date)
        .filter(SalesHistory.date <= last_date)
        .order_by(SalesHistory.date.asc())
        .all()
    )

    for row in history_rows:
        rows_by_date[row.date] = {
            "date": row.date.isoformat(),
            "store_id": row.store_id,
            "product_id": row.product_id,
            "category": row.category,
            "region": row.region,
            "sales": _safe_float(row.sales),
            "price": _safe_float(row.price),
            "stock": _safe_float(row.stock),
            "discount": _safe_float(row.discount),
            "competitor_pricing": _safe_float(row.competitor_pricing),
            "units_ordered": _safe_float(row.units_ordered),
            "weather_condition": row.weather_condition,
            "holiday_promotion": row.holiday_promotion,
            "seasonality": row.seasonality,
            "source": "historique_ventes",
        }

    # ------------------------------------------------------------------
    # Source 2 : ventes + lignes_ventes, les vraies ventes de l'application.
    # ------------------------------------------------------------------
    sale_dates_with_lines: set[date] = set()

    if numeric_product_id is not None:
        sale_rows = (
            db.query(
                func.date(Sale.date_vente).label("sale_date"),
                func.coalesce(func.sum(SaleLine.quantite), 0).label("qty"),
                func.avg(SaleLine.prix_vente_unitaire).label("avg_price"),
            )
            .join(SaleLine, SaleLine.vente_id == Sale.id)
            .filter(SaleLine.produit_id == numeric_product_id)
            .filter(func.date(Sale.date_vente) >= start_date)
            .filter(func.date(Sale.date_vente) <= last_date)
            .group_by(func.date(Sale.date_vente))
            .order_by(func.date(Sale.date_vente).asc())
            .all()
        )

        for sale_date, qty, avg_price in sale_rows:
            if sale_date is None:
                continue

            sale_dates_with_lines.add(sale_date)
            existing = rows_by_date.get(sale_date)

            if existing:
                existing["sales"] = _safe_float(existing.get("sales")) + _safe_float(qty)
                existing["source"] = f"{existing.get('source', '')}+lignes_ventes"
                if not existing.get("price"):
                    existing["price"] = _safe_float(avg_price)
            else:
                rows_by_date[sale_date] = {
                    "date": sale_date.isoformat(),
                    "store_id": "STORE_APPLICATION",
                    "product_id": sku,
                    "category": product.categorie if product else None,
                    "region": "APPLICATION",
                    "sales": _safe_float(qty),
                    "price": _safe_float(avg_price),
                    "stock": _safe_float(product.stock_disponible if product else 0),
                    "discount": 0.0,
                    "competitor_pricing": None,
                    "units_ordered": 0.0,
                    "weather_condition": None,
                    "holiday_promotion": 0,
                    "seasonality": None,
                    "source": "lignes_ventes",
                }

        # ------------------------------------------------------------------
        # Source 3 : mouvement_stock.
        # On ne compte que les sorties justifiées comme vraie vente client.
        # On évite le double comptage si une ligne de vente existe déjà le même jour.
        # ------------------------------------------------------------------
        movement_rows = (
            db.query(
                func.date(StockMovement.date_mouvement).label("movement_date"),
                func.coalesce(func.sum(StockMovement.quantite), 0).label("qty"),
            )
            .filter(StockMovement.produit_id == numeric_product_id)
            .filter(func.upper(StockMovement.type) == "SORTIE")
            .filter(
                func.upper(StockMovement.justification).in_(
                    ["VENTE_CLIENT", "VENTE_CLIENT_DIRECTE", "COMMANDE_CLIENT_LIVREE"]
                )
            )
            .filter(func.date(StockMovement.date_mouvement) >= start_date)
            .filter(func.date(StockMovement.date_mouvement) <= last_date)
            .group_by(func.date(StockMovement.date_mouvement))
            .order_by(func.date(StockMovement.date_mouvement).asc())
            .all()
        )

        for movement_date, qty in movement_rows:
            if movement_date is None or movement_date in sale_dates_with_lines:
                continue

            existing = rows_by_date.get(movement_date)

            if existing:
                existing["sales"] = _safe_float(existing.get("sales")) + _safe_float(qty)
                existing["source"] = f"{existing.get('source', '')}+mouvement_stock_vente_client"
            else:
                rows_by_date[movement_date] = {
                    "date": movement_date.isoformat(),
                    "store_id": "STORE_APPLICATION",
                    "product_id": sku,
                    "category": product.categorie if product else None,
                    "region": "APPLICATION",
                    "sales": _safe_float(qty),
                    "price": _safe_float(product.prix_vente if product else 0),
                    "stock": _safe_float(product.stock_disponible if product else 0),
                    "discount": 0.0,
                    "competitor_pricing": None,
                    "units_ordered": 0.0,
                    "weather_condition": None,
                    "holiday_promotion": 0,
                    "seasonality": None,
                    "source": "mouvement_stock_vente_client",
                }

    rows = list(rows_by_date.values())
    rows.sort(key=lambda item: item["date"])

    return rows[-limit:]
