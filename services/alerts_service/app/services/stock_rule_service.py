from __future__ import annotations

import os
from collections import defaultdict
from datetime import timedelta
from typing import Any, List

from sqlalchemy import create_engine, text

from app.schemas.alert_schemas import AlertCreate

ROLE_MANAGER = "MANAGER"
ROLE_STOCK = "STOCK"
ROLE_PRICING = "PRICING"
MARGIN_TOLERANCE_RATIO = 0.0001


def _f(v, default=0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _i(v, default=0) -> int:
    try:
        if v is None:
            return default
        return int(float(v))
    except Exception:
        return default


def _margin_ratio(value: Any) -> float:
    raw = _f(value, 0.0)
    if raw <= 0:
        return 0.0
    return raw / 100.0 if raw > 1 else raw


def _alert(*, title: str, message: str, alert_type: str, priority: str, role: str, product: dict[str, Any] | None = None, value=None, threshold=None, metadata=None) -> AlertCreate:
    return AlertCreate(
        title=title,
        message=message,
        alert_type=alert_type,
        priority=priority,
        source_service="alerts_service",
        target_role=role,
        product_id=_i(product.get("id"), None) if product else None,
        product_name=product.get("nom") if product else None,
        value=str(value) if value is not None else None,
        threshold=str(threshold) if threshold is not None else None,
        metadata=metadata or {},
    )


class StockRuleService:
    def __init__(self):
        url = os.getenv("STOCK_DATABASE_URL") or os.getenv("STOCK_DB_URL")
        if not url:
            raise RuntimeError("STOCK_DATABASE_URL manquant dans alerts_service")
        self.engine = create_engine(url, pool_pre_ping=True)
        self.last_details = {}

    def _load_products(self, conn):
        return [dict(r._mapping) for r in conn.execute(text('''
            SELECT id, sku, nom, categorie, marque,
                   "prixCout" AS prix_cout,
                   "prixVente" AS prix_vente,
                   "margeReservee" AS marge_reservee,
                   "stockDisponible" AS stock_disponible,
                   "stockMinimum" AS stock_minimum,
                   "seuilMin" AS seuil_min,
                   "seuilMax" AS seuil_max
            FROM produits
            WHERE COALESCE(statut, 'actif') NOT IN ('SUPPRIME', 'ARCHIVE')
        '''))]

    def _load_sales_stats(self, conn):
        max_date = conn.execute(text('SELECT MAX("dateVente") FROM ventes')).scalar()
        if not max_date:
            return {}, None
        since_30 = max_date - timedelta(days=30)
        rows = conn.execute(text('''
            SELECT lv.produit_id,
                   SUM(lv.quantite) AS qty_30,
                   COUNT(DISTINCT DATE(v."dateVente")) AS active_days
            FROM lignes_ventes lv
            JOIN ventes v ON v.id = lv.vente_id
            WHERE v."dateVente" >= :since_30
              AND COALESCE(v.statut, 'VALIDEE') NOT IN ('ANNULEE', 'CANCELLED')
            GROUP BY lv.produit_id
        '''), {"since_30": since_30}).all()
        stats = {}
        for r in rows:
            qty = _f(r.qty_30)
            stats[int(r.produit_id)] = {"qty_30": qty, "avg_daily_sales": qty / 30.0, "active_days": _i(r.active_days), "max_sale_date": max_date.isoformat() if hasattr(max_date, "isoformat") else str(max_date)}
        return stats, max_date

    def generate_alerts(self) -> List[AlertCreate]:
        alerts: List[AlertCreate] = []
        details = defaultdict(int)
        with self.engine.connect() as conn:
            products = self._load_products(conn)
            sales_stats, _ = self._load_sales_stats(conn)
        for p in products:
            pid = _i(p.get("id"))
            stock = _f(p.get("stock_disponible"))
            seuil_min = _f(p.get("seuil_min") if p.get("seuil_min") is not None else p.get("stock_minimum"))
            seuil_max = _f(p.get("seuil_max"))
            prix_cout = _f(p.get("prix_cout"))
            prix_vente = _f(p.get("prix_vente"))
            min_margin_ratio = _margin_ratio(p.get("marge_reservee"))
            s = sales_stats.get(pid, {})
            avg_daily = _f(s.get("avg_daily_sales"))
            qty_30 = _f(s.get("qty_30"))
            meta = {"qty_30": qty_30, "avg_daily_sales": avg_daily, "max_sale_date": s.get("max_sale_date")}

            if seuil_min > 0 and stock < seuil_min:
                priority = "CRITICAL" if qty_30 >= 10 or avg_daily >= 1 else "IMPORTANT"
                alerts.append(_alert(title="Rupture de stock", message=f"Le stock de {p['nom']} est inférieur au seuil minimum ({stock:g} < {seuil_min:g}).", alert_type="STOCK_OUT", priority=priority, role=ROLE_STOCK, product=p, value=stock, threshold=seuil_min, metadata=meta))
                details["STOCK_OUT"] += 1

            if seuil_max > 0 and stock > seuil_max:
                priority = "CRITICAL" if stock >= 2 * seuil_max and qty_30 <= 3 else ("IMPORTANT" if stock >= 1.2 * seuil_max else "MEDIUM")
                alerts.append(_alert(title="Surstockage détecté", message=f"Le stock de {p['nom']} dépasse le seuil maximal ({stock:g} > {seuil_max:g}).", alert_type="OVERSTOCK", priority=priority, role=ROLE_STOCK, product=p, value=stock, threshold=seuil_max, metadata=meta))
                details["OVERSTOCK"] += 1

            if stock > 0 and avg_daily > 0:
                days_left = stock / avg_daily
                if days_left <= 14:
                    priority = "CRITICAL" if days_left <= 3 else ("IMPORTANT" if days_left <= 7 else "MEDIUM")
                    alerts.append(_alert(title="Risque de rupture future", message=f"Le produit {p['nom']} risque d’être en rupture dans environ {days_left:.1f} jour(s).", alert_type="FUTURE_STOCKOUT", priority=priority, role=ROLE_STOCK, product=p, value=f"{days_left:.1f}", threshold="14 jours", metadata=meta))
                    details["FUTURE_STOCKOUT"] += 1

            margin = None
            margin_gap = 0.0
            if prix_vente > 0 and prix_cout > 0:
                # Règle métier du projet :
                # margeReservee = marge minimale sur coût.
                # Exemple : coût 3000, prix 3700 => (3700 - 3000) / 3000 = 23.33%.
                # Donc une marge minimale de 20% est respectée.
                margin = (prix_vente - prix_cout) / prix_cout
                margin_gap = min_margin_ratio - margin

            signals = []
            if seuil_max > 0 and stock >= 2 * seuil_max and qty_30 <= 3:
                signals.append("stock élevé + ventes faibles")
            if stock > 0 and qty_30 <= 1 and seuil_max > 0 and stock > seuil_max:
                signals.append("rotation faible")
            if margin is not None and min_margin_ratio > 0 and margin_gap > MARGIN_TOLERANCE_RATIO:
                signals.append("marge faible")
            very_strong = seuil_max > 0 and stock >= 3 * seuil_max and qty_30 == 0
            if len(signals) >= 2 or very_strong:
                priority = "CRITICAL" if len(signals) >= 3 or very_strong else "IMPORTANT"
                for role in (ROLE_STOCK, ROLE_MANAGER):
                    alerts.append(_alert(title="Produit à risque", message=f"{p['nom']} présente un risque : {', '.join(signals) if signals else 'stock très élevé sans ventes'}.", alert_type="RISKY_PRODUCT", priority=priority, role=role, product=p, value=len(signals), threshold="2 signaux", metadata={**meta, "signals": signals, "margin": margin}))
                details["RISKY_PRODUCT"] += 1

            if margin is not None and min_margin_ratio > 0 and margin_gap > MARGIN_TOLERANCE_RATIO:
                priority = "CRITICAL" if margin <= 0 else ("IMPORTANT" if margin < min_margin_ratio * 0.5 else "MEDIUM")
                message = f"La marge sur coût de {p['nom']} est inférieure à la marge minimale ({margin * 100:.2f}% < {min_margin_ratio * 100:.2f}%)."
                for role in (ROLE_PRICING, ROLE_MANAGER):
                    alerts.append(_alert(title="Marge non respectée", message=message, alert_type="MARGIN_VIOLATION", priority=priority, role=role, product=p, value=f"{margin:.4f}", threshold=f"{min_margin_ratio:.4f}", metadata={**meta, "margin_gap": margin_gap, "margin_formula": "(prix_vente - prix_cout) / prix_cout"}))
                details["MARGIN_VIOLATION"] += 1
        self.last_details = dict(details)
        return alerts
