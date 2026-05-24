from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.tables import (
    Product,
    SalesHistory,
    Sale,
    SaleLine,
    StockMovement,
)


SALE_MOVEMENT_JUSTIFICATIONS = {
    "VENTE_CLIENT",
    "VENTE_CLIENT_DIRECTE",
    "COMMANDE_CLIENT_LIVREE",
}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _get_latest_available_date(product: Product, db: Session):
    """
    Date d'ancrage des KPI.

    On n'utilise pas uniquement la date du jour, car la base peut contenir
    des données historiques. On prend la dernière date disponible depuis :
    - historique_ventes
    - ventes + lignes_ventes
    - mouvement_stock avec SORTIE + VENTE_CLIENT
    """
    dates = []

    if product.sku:
        max_history_date = (
            db.query(func.max(SalesHistory.date))
            .filter(SalesHistory.produit_id == product.sku)
            .scalar()
        )
        if max_history_date:
            dates.append(max_history_date)

    max_sale_date = (
        db.query(func.max(func.date(Sale.date_vente)))
        .join(SaleLine, SaleLine.vente_id == Sale.id)
        .filter(SaleLine.produit_id == product.id)
        .scalar()
    )
    if max_sale_date:
        dates.append(max_sale_date)

    max_movement_date = (
        db.query(func.max(func.date(StockMovement.date_mouvement)))
        .filter(StockMovement.produit_id == product.id)
        .filter(func.upper(StockMovement.type) == "SORTIE")
        .filter(
            func.upper(StockMovement.justification).in_(
                list(SALE_MOVEMENT_JUSTIFICATIONS)
            )
        )
        .scalar()
    )
    if max_movement_date:
        dates.append(max_movement_date)

    if not dates:
        return None

    return max(dates)


def _velocity_label(daily_velocity: float) -> str:
    """
    Lecture simple de la vitesse de vente.
    Les seuils sont volontairement génériques et peuvent être adaptés par catégorie.
    """
    value = _safe_float(daily_velocity, 0.0)

    if value <= 0:
        return "Aucune vitesse"
    if value < 0.15:
        return "Très lente"
    if value < 0.5:
        return "Lente"
    if value < 1.0:
        return "Moyenne"
    if value < 3.0:
        return "Rapide"
    return "Très rapide"


def get_product_kpis_service(product_id: int, db: Session, days: int = 30) -> dict:
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise ValueError(f"Produit introuvable avec id={product_id}")

    if not product.sku:
        raise ValueError("Le produit n'a pas de SKU, impossible de calculer les KPI.")

    days = int(days or 30)
    if days <= 0:
        days = 30

    end_date = _get_latest_available_date(product, db)
    current_stock = _safe_float(product.stock_disponible, 0)

    if not end_date:
        return {
            "product_id": product.id,
            "sku": product.sku,
            "name": product.nom,
            "period_days": days,
            "quantity_sold": 0,
            "avg_daily_sales": 0,
            "sale_velocity_daily": 0,
            "sale_velocity_weekly": 0,
            "sale_velocity_monthly": 0,
            "sales_velocity_label": "Aucune vitesse",
            "velocity_source": "none",
            "avg_stock": round(current_stock, 2),
            "stock_rotation": 0,
            "stock_coverage_days": None,
            "current_stock": round(current_stock, 2),
            "history_rows_count": 0,
            "matching_mode": "unified",
            "analysis_start_date": None,
            "analysis_end_date": None,
            "sources": [],
        }

    start_date = end_date - timedelta(days=days - 1)

    rows_by_date = {}
    sources = set()

    # ==========================================================
    # 1. Historique importé CSV : historique_ventes
    # ==========================================================
    history_rows = (
        db.query(SalesHistory)
        .filter(SalesHistory.produit_id == product.sku)
        .filter(SalesHistory.date >= start_date)
        .filter(SalesHistory.date <= end_date)
        .order_by(SalesHistory.date.asc())
        .all()
    )

    for row in history_rows:
        row_date = row.date
        rows_by_date[row_date] = {
            "date": row_date,
            "sales": _safe_float(row.ventes, 0),
            "stock": _safe_float(row.stock, current_stock),
            "source": "historique_ventes",
        }
        sources.add("historique_ventes")

    # ==========================================================
    # 2. Ventes réelles : ventes + lignes_ventes
    # ==========================================================
    sale_rows = (
        db.query(
            func.date(Sale.date_vente).label("sale_date"),
            func.sum(SaleLine.quantite).label("qty"),
        )
        .join(SaleLine, SaleLine.vente_id == Sale.id)
        .filter(SaleLine.produit_id == product.id)
        .filter(func.date(Sale.date_vente) >= start_date)
        .filter(func.date(Sale.date_vente) <= end_date)
        .group_by(func.date(Sale.date_vente))
        .order_by(func.date(Sale.date_vente).asc())
        .all()
    )

    sale_dates = set()

    for sale_date, qty in sale_rows:
        sale_dates.add(sale_date)
        qty_float = _safe_float(qty, 0)

        if sale_date in rows_by_date:
            rows_by_date[sale_date]["sales"] += qty_float
            rows_by_date[sale_date]["source"] += "+lignes_ventes"
        else:
            rows_by_date[sale_date] = {
                "date": sale_date,
                "sales": qty_float,
                "stock": current_stock,
                "source": "lignes_ventes",
            }

        sources.add("lignes_ventes")

    # ==========================================================
    # 3. Mouvements stock considérés comme ventes
    # ==========================================================
    # Seulement : SORTIE + VENTE_CLIENT / COMMANDE_CLIENT_LIVREE
    # Si une ligne de vente existe déjà le même jour, on ignore le mouvement
    # pour éviter le double comptage.
    # ==========================================================
    movement_rows = (
        db.query(
            func.date(StockMovement.date_mouvement).label("movement_date"),
            func.sum(StockMovement.quantite).label("qty"),
        )
        .filter(StockMovement.produit_id == product.id)
        .filter(func.upper(StockMovement.type) == "SORTIE")
        .filter(
            func.upper(StockMovement.justification).in_(
                list(SALE_MOVEMENT_JUSTIFICATIONS)
            )
        )
        .filter(func.date(StockMovement.date_mouvement) >= start_date)
        .filter(func.date(StockMovement.date_mouvement) <= end_date)
        .group_by(func.date(StockMovement.date_mouvement))
        .order_by(func.date(StockMovement.date_mouvement).asc())
        .all()
    )

    for movement_date, qty in movement_rows:
        if movement_date in sale_dates:
            continue

        qty_float = _safe_float(qty, 0)

        if movement_date in rows_by_date:
            rows_by_date[movement_date]["sales"] += qty_float
            rows_by_date[movement_date]["source"] += "+mouvement_stock"
        else:
            rows_by_date[movement_date] = {
                "date": movement_date,
                "sales": qty_float,
                "stock": current_stock,
                "source": "mouvement_stock_vente_client",
            }

        sources.add("mouvement_stock_vente_client")

    rows = list(rows_by_date.values())
    rows.sort(key=lambda item: item["date"])

    quantity_sold = sum(_safe_float(row.get("sales"), 0) for row in rows)

    # ==========================================================
    # VITESSE DE VENTE
    # ==========================================================
    # Vitesse quotidienne = quantité vendue / nombre de jours analysés
    # Vitesse hebdomadaire = vitesse quotidienne * 7
    # Vitesse mensuelle = vitesse quotidienne * 30
    # ==========================================================
    sale_velocity_daily = quantity_sold / days if days > 0 else 0.0
    sale_velocity_weekly = sale_velocity_daily * 7
    sale_velocity_monthly = sale_velocity_daily * 30

    # Alias historique conservé pour ne pas casser le front existant.
    avg_daily_sales = sale_velocity_daily

    stock_values = [
        _safe_float(row.get("stock"), current_stock)
        for row in rows
        if row.get("stock") is not None
    ]

    avg_stock = (
        sum(stock_values) / len(stock_values)
        if stock_values
        else current_stock
    )

    stock_rotation = quantity_sold / avg_stock if avg_stock > 0 else 0.0

    stock_coverage_days = (
        current_stock / sale_velocity_daily
        if sale_velocity_daily > 0
        else None
    )

    if "lignes_ventes" in sources:
        velocity_source = "lignes_ventes"
    elif "mouvement_stock_vente_client" in sources:
        velocity_source = "mouvement_stock_vente_client"
    elif "historique_ventes" in sources:
        velocity_source = "historique_ventes"
    else:
        velocity_source = "none"

    return {
        "product_id": product.id,
        "sku": product.sku,
        "name": product.nom,
        "period_days": days,

        # KPI principaux
        "quantity_sold": round(quantity_sold, 2),
        "avg_daily_sales": round(avg_daily_sales, 2),

        # Nouveaux champs vitesse de vente
        "sale_velocity_daily": round(sale_velocity_daily, 2),
        "sale_velocity_weekly": round(sale_velocity_weekly, 2),
        "sale_velocity_monthly": round(sale_velocity_monthly, 2),
        "sales_velocity_label": _velocity_label(sale_velocity_daily),
        "velocity_source": velocity_source,

        # Stock / rotation
        "avg_stock": round(avg_stock, 2),
        "stock_rotation": round(stock_rotation, 2),
        "stock_coverage_days": (
            round(stock_coverage_days, 2)
            if stock_coverage_days is not None
            else None
        ),
        "current_stock": round(current_stock, 2),

        # Infos techniques utiles au front
        "history_rows_count": len(rows),
        "matching_mode": "unified",
        "analysis_start_date": str(start_date),
        "analysis_end_date": str(end_date),
        "sources": sorted(list(sources)),
    }
