from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.models.tables import (
    Competitor,
    Product,
    ProductPromotion,
    Promotion,
    Sale,
    SaleLine,
    SalesHistory,
)
from app.services.dashboard_filter_service import DashboardFilterService


# ==========================================================
# Helpers génériques
# ==========================================================

def safe_round(value: float | int | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def pct(num: float | int, den: float | int) -> float | None:
    if not den:
        return None
    return round((float(num) / float(den)) * 100, 2)


def iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


# ==========================================================
# Dashboard service simple et robuste
# ==========================================================

class DashboardMetricsService:
    def __init__(self, db: Session):
        self.db = db

    # ======================================================
    # Contrat API stable
    # ======================================================

    def _kpi(
        self,
        key: str,
        label: str,
        value: Any,
        unit: str = "",
        status: str = "neutral",
        description: str = "",
        delta: float | None = None,
        trend: str = "stable",
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "value": value,
            "unit": unit,
            "delta": delta,
            "trend": trend,
            "status": status,
            "description": description,
        }

    def _contract(
        self,
        f: dict[str, Any],
        kpis: list[dict[str, Any]],
        charts: dict[str, Any],
        tables: dict[str, Any],
        insights: list[dict[str, Any]],
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "filters": {
                "period_days": f.get("period_days"),
                "period_label": f"{f.get('period_days')} derniers jours disponibles",
                "start_date": iso(f.get("start_date")),
                "end_date": iso(f.get("end_date")),
                "data_source": f.get("data_source", "none"),
                "available": self.filters(),
            },
            "kpis": kpis,
            "charts": charts,
            "tables": tables,
            "insights": insights,
            "warnings": warnings or [],
            "updated_at": datetime.utcnow().isoformat(),
        }

    # ======================================================
    # Filtres disponibles
    # ======================================================

    def filters(self) -> dict[str, Any]:
        categories = [
            row.categorie
            for row in (
                self.db.query(Product.categorie.label("categorie"))
                .filter(Product.categorie.isnot(None))
                .distinct()
                .order_by(Product.categorie.asc())
                .all()
            )
            if row.categorie
        ]

        marques = [
            row.marque
            for row in (
                self.db.query(Product.marque.label("marque"))
                .filter(Product.marque.isnot(None))
                .distinct()
                .order_by(Product.marque.asc())
                .all()
            )
            if row.marque
        ]

        return {
            "periods": [
                {"value": 7, "label": "7 derniers jours disponibles"},
                {"value": 30, "label": "30 derniers jours disponibles"},
                {"value": 90, "label": "90 derniers jours disponibles"},
                {"value": 180, "label": "6 derniers mois disponibles"},
                {"value": 365, "label": "12 derniers mois disponibles"},
            ],
            "categories": [{"value": c, "label": c} for c in categories],
            "marques": [{"value": m, "label": m} for m in marques],
            "statut_stock": [
                {"value": "rupture", "label": "Rupture"},
                {"value": "critique", "label": "Critique"},
                {"value": "normal", "label": "Normal"},
                {"value": "surstock", "label": "Surstock"},
            ],
            "statut_promotion": [
                {"value": "en_promotion", "label": "En promotion"},
                {"value": "hors_promotion", "label": "Hors promotion"},
            ],
            "position_marche": [
                {"value": "sous_marche", "label": "Sous le marché"},
                {"value": "aligne", "label": "Aligné"},
                {"value": "au_dessus", "label": "Au-dessus du marché"},
            ],
        }

    # ======================================================
    # Produits
    # ======================================================

    def _products(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        q = self.db.query(
            Product.id.label("id"),
            Product.sku.label("sku"),
            Product.nom.label("nom"),
            Product.categorie.label("categorie"),
            Product.marque.label("marque"),
            Product.description.label("description"),
            Product.prix_cout.label("prixCout"),
            Product.prix_vente.label("prixVente"),
            Product.stock_disponible.label("stockDisponible"),
            Product.stock_reserve.label("stockReserve"),
            Product.stock_minimum.label("stockMinimum"),
            Product.seuil_max.label("seuilMax"),
            Product.seuil_min.label("seuilMin"),
            Product.statut.label("statut"),
        )

        if filters.get("categorie"):
            q = q.filter(Product.categorie == filters["categorie"])

        if filters.get("marque"):
            q = q.filter(Product.marque == filters["marque"])

        rows = q.order_by(Product.nom.asc()).all()

        products = [
            {
                "id": row.id,
                "sku": row.sku,
                "nom": row.nom,
                "categorie": row.categorie,
                "marque": row.marque,
                "description": row.description,
                "prixCout": row.prixCout,
                "prixVente": row.prixVente,
                "stockDisponible": row.stockDisponible,
                "stockReserve": row.stockReserve,
                "stockMinimum": row.stockMinimum,
                "seuilMax": row.seuilMax,
                "seuilMin": row.seuilMin,
                "statut": row.statut,
            }
            for row in rows
        ]

        if filters.get("statut_stock"):
            products = [
                p for p in products
                if self._stock_status(p) == filters["statut_stock"]
            ]

        return products

    def _resolve_period_from_data(
        self,
        products: list[dict[str, Any]],
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        product_ids = [p["id"] for p in products if p.get("id") is not None]
        skus = [p["sku"] for p in products if p.get("sku")]

        candidates: list[date] = []

        if product_ids:
            latest_sale_dt = (
                self.db.query(func.max(Sale.date_vente))
                .join(SaleLine, SaleLine.vente_id == Sale.id)
                .filter(SaleLine.produit_id.in_(product_ids))
                .scalar()
            )
            if latest_sale_dt:
                candidates.append(
                    latest_sale_dt.date()
                    if hasattr(latest_sale_dt, "date")
                    else latest_sale_dt
                )

        if skus:
            latest_history_date = (
                self.db.query(func.max(SalesHistory.date))
                .filter(SalesHistory.produit_id.in_(skus))
                .scalar()
            )
            if latest_history_date:
                candidates.append(latest_history_date)

        end_date = max(candidates) if candidates else date.today()
        period_days = as_int(filters.get("period_days"), 30)
        start_date = end_date - timedelta(days=period_days - 1)

        resolved = dict(filters)
        resolved["period_days"] = period_days
        resolved["start_date"] = start_date
        resolved["end_date"] = end_date

        return resolved

    def _base(
        self,
        params: dict[str, Any],
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        str,
        list[dict[str, Any]],
        dict[int, dict[str, Any]],
        dict[int, dict[str, Any]],
        list[str],
    ]:
        filters = DashboardFilterService.normalize(params)
        products = self._products(filters)
        filters = self._resolve_period_from_data(products, filters)

        sales_source, sales, sales_warnings = self._sales_rows(products, filters)
        filters["data_source"] = (
            "sales_history" if sales_source == "historique_ventes" else sales_source
        )

        product_ids = [p["id"] for p in products if p.get("id") is not None]

        promos = self._active_promotions_by_product(product_ids, filters["end_date"])
        market = self._competitor_market(product_ids)

        if filters.get("statut_promotion") == "en_promotion":
            products = [p for p in products if p.get("id") in promos]

        elif filters.get("statut_promotion") == "hors_promotion":
            products = [p for p in products if p.get("id") not in promos]

        if filters.get("position_marche"):
            products = [
                p for p in products
                if self._market_position(p, market.get(p.get("id"))) == filters["position_marche"]
            ]

        keep_ids = {p["id"] for p in products if p.get("id") is not None}
        sales = [
            r for r in sales
            if r.get("product_id") in keep_ids or r.get("product_id") is None
        ]

        return filters, products, sales_source, sales, promos, market, sales_warnings

    # ======================================================
    # Données DB
    # ======================================================

    @staticmethod
    def _stock_status(product: dict[str, Any]) -> str:
        stock = as_float(product.get("stockDisponible"), 0)
        seuil_min = (
            product.get("seuilMin")
            if product.get("seuilMin") is not None
            else product.get("stockMinimum")
        )
        seuil_max = product.get("seuilMax")

        if stock <= 0:
            return "rupture"

        if seuil_min is not None and stock <= as_float(seuil_min):
            return "critique"

        if seuil_max is not None and stock >= as_float(seuil_max):
            return "surstock"

        return "normal"

    def _active_promotions_by_product(
        self,
        product_ids: list[int],
        current_date: date,
    ) -> dict[int, dict[str, Any]]:
        if not product_ids:
            return {}

        rows = (
            self.db.query(
                ProductPromotion.produit_id.label("produit_id"),
                ProductPromotion.prix_promo.label("prix_promo_ligne"),
                Promotion.id.label("promotion_id"),
                Promotion.nom.label("nom"),
                Promotion.type.label("type"),
                Promotion.valeur.label("valeur"),
                Promotion.prix_promo.label("prix_promo"),
                Promotion.date_fin.label("date_fin"),
            )
            .join(Promotion, Promotion.id == ProductPromotion.promotion_id)
            .filter(
                ProductPromotion.produit_id.in_(product_ids),
                Promotion.actif.is_(True),
                or_(Promotion.date_debut.is_(None), Promotion.date_debut <= current_date),
                or_(Promotion.date_fin.is_(None), Promotion.date_fin >= current_date),
            )
            .all()
        )

        return {
            int(row.produit_id): {
                "promotion_id": row.promotion_id,
                "nom": row.nom,
                "type": row.type,
                "valeur": row.valeur,
                "prix_promo": row.prix_promo_ligne or row.prix_promo,
                "date_fin": iso(row.date_fin),
            }
            for row in rows
        }

    def _sales_rows(
        self,
        products: list[dict[str, Any]],
        filters: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        """
        Source principale : sales_history.

        Important pour ton projet : la table remplie en base est `sales_history`,
        donc on lit d'abord cette table. Les tables `ventes/lignes_ventes` ne sont
        utilisées qu'en fallback si `sales_history` ne contient aucune ligne sur
        la période sélectionnée.
        """
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []

        product_ids = [p["id"] for p in products if p.get("id") is not None]
        by_id = {p["id"]: p for p in products if p.get("id") is not None}

        skus = [p["sku"] for p in products if p.get("sku")]
        by_sku = {p["sku"]: p for p in products if p.get("sku")}

        # 1) PRIORITÉ : sales_history, car c'est la table réellement remplie.
        if skus:
            history_rows = (
                self.db.query(
                    SalesHistory.date.label("date"),
                    SalesHistory.produit_id.label("product_sku"),
                    SalesHistory.categorie.label("category"),
                    SalesHistory.ventes.label("sales"),
                    SalesHistory.prix.label("price"),
                    SalesHistory.stock.label("stock"),
                )
                .filter(SalesHistory.produit_id.in_(skus))
                .filter(SalesHistory.date >= filters["start_date"])
                .filter(SalesHistory.date <= filters["end_date"])
                .all()
            )

            for row in history_rows:
                product = by_sku.get(row.product_sku)
                quantity = as_float(row.sales)
                fallback_price = product.get("prixVente") if product else 0
                price = as_float(row.price, as_float(fallback_price))

                rows.append(
                    {
                        "date": row.date,
                        "product_id": product.get("id") if product else None,
                        "sku": row.product_sku,
                        "categorie": (
                            row.category
                            or (product.get("categorie") if product else None)
                            or "Sans catégorie"
                        ),
                        "units": quantity,
                        "revenue": quantity * price,
                        "price": price,
                        "source": "sales_history",
                        "stock_snapshot": as_float(row.stock) if row.stock is not None else None,
                    }
                )

            if rows:
                # Message non bloquant uniquement si la colonne stock est vide dans sales_history.
                if not any(r.get("stock_snapshot") is not None for r in rows):
                    warnings.append(
                        "Les ventes sont bien lues depuis sales_history, mais la colonne stock est vide "
                        "sur cette période. Le graphique stock_vs_sales affiche stock_avg = null."
                    )
                return "sales_history", rows, warnings

        # 2) Fallback seulement si sales_history ne donne rien.
        # Ce fallback garde l'ancien comportement sans casser les installations qui utilisent ventes/lignes_ventes.
        start_dt = datetime.combine(filters["start_date"], time.min)
        end_dt = datetime.combine(filters["end_date"], time.max)

        stock_by_sku_day: dict[tuple[str, date], float] = {}

        if skus:
            stock_rows = (
                self.db.query(
                    SalesHistory.produit_id.label("product_sku"),
                    SalesHistory.date.label("date"),
                    func.avg(SalesHistory.stock).label("avg_stock"),
                )
                .filter(SalesHistory.produit_id.in_(skus))
                .filter(SalesHistory.date >= filters["start_date"])
                .filter(SalesHistory.date <= filters["end_date"])
                .filter(SalesHistory.stock.isnot(None))
                .group_by(SalesHistory.produit_id, SalesHistory.date)
                .all()
            )

            stock_by_sku_day = {
                (row.product_sku, row.date): as_float(row.avg_stock)
                for row in stock_rows
            }

        if product_ids:
            sale_rows = (
                self.db.query(
                    Sale.date_vente.label("date_vente"),
                    SaleLine.produit_id.label("produit_id"),
                    Product.categorie.label("categorie"),
                    Product.sku.label("sku"),
                    SaleLine.quantite.label("quantite"),
                    SaleLine.prix_vente_unitaire.label("prix_vente_unitaire"),
                )
                .join(SaleLine, SaleLine.vente_id == Sale.id)
                .join(Product, Product.id == SaleLine.produit_id)
                .filter(SaleLine.produit_id.in_(product_ids))
                .filter(Sale.date_vente >= start_dt)
                .filter(Sale.date_vente <= end_dt)
                .all()
            )

            for row in sale_rows:
                product = by_id.get(row.produit_id)
                day = row.date_vente.date() if row.date_vente else filters["end_date"]

                quantity = as_float(row.quantite)
                fallback_price = product.get("prixVente") if product else 0
                price = as_float(row.prix_vente_unitaire, as_float(fallback_price))

                rows.append(
                    {
                        "date": day,
                        "product_id": row.produit_id,
                        "sku": row.sku,
                        "categorie": row.categorie or "Sans catégorie",
                        "units": quantity,
                        "revenue": quantity * price,
                        "price": price,
                        "source": "ventes",
                        "stock_snapshot": stock_by_sku_day.get((row.sku, day)),
                    }
                )

        if rows:
            warnings.append(
                "Aucune ligne sales_history trouvée pour cette période : fallback ventes/lignes_ventes utilisé."
            )
            return "ventes", rows, warnings

        if not skus:
            return "none", [], [
                "Aucun SKU produit disponible pour chercher les ventes dans sales_history."
            ]

        warnings.append(
            "Aucune vente trouvée dans sales_history pour la période calculée."
        )
        return "none", [], warnings

    def _competitor_market(self, product_ids: list[int]) -> dict[int, dict[str, Any]]:

        if not product_ids:
            return {}

        rows = self.db.execute(
            text(
                """
                SELECT
                    pc.produit_id AS produit_id,
                    AVG(pc."prixConcurrent") AS avg_price,
                    MIN(pc."prixConcurrent") AS min_price,
                    MAX(pc."prixConcurrent") AS max_price,
                    COUNT(pc.id) AS count,
                    MAX(pc."dateCollecte") AS last_collect
                FROM produits_concurrents pc
                WHERE pc.produit_id = ANY(:product_ids)
                  AND pc."prixConcurrent" IS NOT NULL
                  AND COALESCE(pc.fiable, true) IS true
                GROUP BY pc.produit_id
                """
            ),
            {"product_ids": product_ids},
        ).mappings().all()

        return {
            int(row["produit_id"]): {
                "avg_price": as_float(row["avg_price"]),
                "min_price": as_float(row["min_price"]),
                "max_price": as_float(row["max_price"]),
                "count": as_int(row["count"]),
                "last_collect": iso(row["last_collect"]),
            }
            for row in rows
        }

    def _latest_competitor_sources(self) -> list[dict[str, Any]]:
        rows = (
            self.db.query(
                Competitor.id.label("id"),
                Competitor.nom.label("nom"),
                Competitor.actif.label("actif"),
                Competitor.dernier_scraping.label("dernier_scraping"),
            )
            .order_by(Competitor.nom.asc())
            .all()
        )

        return [
            {
                "id": row.id,
                "nom": row.nom,
                "actif": row.actif,
                "dernier_scraping": iso(row.dernier_scraping),
                "status": "active" if row.actif else "inactive",
            }
            for row in rows
        ]

    # ======================================================
    # Grouping charts
    # ======================================================

    @staticmethod
    def _group_sales_by_day(sales: list[dict[str, Any]]) -> list[dict[str, Any]]:
        acc = defaultdict(
            lambda: {
                "units": 0.0,
                "revenue": 0.0,
                "stock": 0.0,
                "stock_count": 0,
            }
        )

        for row in sales:
            key = iso(row["date"])

            acc[key]["units"] += as_float(row.get("units"))
            acc[key]["revenue"] += as_float(row.get("revenue"))

            if row.get("stock_snapshot") is not None:
                acc[key]["stock"] += as_float(row["stock_snapshot"])
                acc[key]["stock_count"] += 1

        return [
            {
                "date": key,
                "units": round(value["units"], 2),
                "revenue": round(value["revenue"], 2),
                "stock_avg": (
                    round(value["stock"] / value["stock_count"], 2)
                    if value["stock_count"]
                    else None
                ),
            }
            for key, value in sorted(acc.items())
        ]

    @staticmethod
    def _group_sales_by_category(sales: list[dict[str, Any]]) -> list[dict[str, Any]]:
        acc = defaultdict(lambda: {"units": 0.0, "revenue": 0.0})

        for row in sales:
            key = row.get("categorie") or "Sans catégorie"
            acc[key]["units"] += as_float(row.get("units"))
            acc[key]["revenue"] += as_float(row.get("revenue"))

        return [
            {
                "categorie": key,
                "units": round(value["units"], 2),
                "revenue": round(value["revenue"], 2),
            }
            for key, value in sorted(
                acc.items(),
                key=lambda item: item[1]["revenue"],
                reverse=True,
            )
        ]

    @staticmethod
    def _avg_historical_stock(sales: list[dict[str, Any]]) -> float | None:
        values = [
            as_float(row["stock_snapshot"])
            for row in sales
            if row.get("stock_snapshot") is not None
        ]

        return mean(values) if values else None

    # ======================================================
    # Pricing helpers
    # ======================================================

    @staticmethod
    def _margin_pct(product: dict[str, Any]) -> float | None:
        prix_vente = product.get("prixVente")
        prix_cout = product.get("prixCout")

        if not prix_vente or as_float(prix_vente) <= 0 or prix_cout is None:
            return None

        return ((as_float(prix_vente) - as_float(prix_cout)) / as_float(prix_vente)) * 100

    @staticmethod
    def _market_position(
        product: dict[str, Any],
        market: dict[str, Any] | None,
    ) -> str | None:
        prix_vente = product.get("prixVente")

        if not prix_vente or not market or not market.get("avg_price"):
            return None

        avg_price = as_float(market["avg_price"])
        price = as_float(prix_vente)

        if price < avg_price * 0.97:
            return "sous_marche"

        if price > avg_price * 1.03:
            return "au_dessus"

        return "aligne"

    def _price_evolution(
        self,
        sales: list[dict[str, Any]],
        market: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = self._group_sales_by_day(sales)

        for row in rows:
            same_day = [
                sale for sale in sales
                if iso(sale["date"]) == row["date"]
            ]

            internal_prices = [
                as_float(sale["price"])
                for sale in same_day
                if sale.get("price")
            ]

            competitor_prices = []

            for sale in same_day:
                item = market.get(sale.get("product_id"))

                if item and item.get("avg_price"):
                    competitor_prices.append(as_float(item["avg_price"]))

            row["prix_interne_moyen"] = (
                safe_round(mean(internal_prices), 2)
                if internal_prices
                else None
            )

            row["prix_concurrent_moyen"] = (
                safe_round(mean(competitor_prices), 2)
                if competitor_prices
                else None
            )

        return rows

    # ======================================================
    # Dashboard Stock
    # ======================================================

    def stock_dashboard(self, params: dict[str, Any]) -> dict[str, Any]:
        f, products, sales_source, sales, promos, market, data_warnings = self._base(params)

        total_products = len(products)
        period_days = as_int(f.get("period_days"), 30)

        statuses = defaultdict(int)
        for product in products:
            statuses[self._stock_status(product)] += 1

        total_units = sum(as_float(row.get("units")) for row in sales)
        revenue = sum(as_float(row.get("revenue")) for row in sales)
        avg_daily_sales = total_units / period_days if period_days else None

        current_stock_available = sum(as_float(p.get("stockDisponible")) for p in products)
        current_stock_reserved = sum(as_float(p.get("stockReserve")) for p in products)
        current_stock_on_hand = current_stock_available + current_stock_reserved
        avg_stock_historical = self._avg_historical_stock(sales)
        current_avg_stock = mean([as_float(p.get("stockDisponible")) for p in products]) if products else None
        stock_reference = avg_stock_historical if avg_stock_historical is not None else current_avg_stock

        rotation = (total_units / stock_reference) if stock_reference else None
        coverage_days = (current_stock_available / avg_daily_sales) if avg_daily_sales else None
        sell_through_rate = pct(total_units, total_units + current_stock_available)
        rupture_rate = pct(statuses["rupture"], total_products)
        overstock_rate = pct(statuses["surstock"], total_products)
        available_rate = pct(current_stock_available, current_stock_on_hand)
        execution_rate = pct(statuses["normal"] + statuses["surstock"], total_products)

        sales_by_product = defaultdict(float)
        revenue_by_product = defaultdict(float)
        sales_by_sku = defaultdict(float)
        for row in sales:
            if row.get("product_id"):
                sales_by_product[row["product_id"]] += as_float(row.get("units"))
                revenue_by_product[row["product_id"]] += as_float(row.get("revenue"))
            if row.get("sku"):
                sales_by_sku[row["sku"]] += as_float(row.get("units"))

        product_lookup = {p.get("id"): p for p in products if p.get("id") is not None}

        top_products_sold = [
            {
                "id": pid,
                "produit": product_lookup.get(pid, {}).get("nom") or f"Produit {pid}",
                "sku": product_lookup.get(pid, {}).get("sku"),
                "categorie": product_lookup.get(pid, {}).get("categorie") or "Sans catégorie",
                "units": safe_round(units, 0),
                "revenue": safe_round(revenue_by_product.get(pid), 2),
            }
            for pid, units in sorted(sales_by_product.items(), key=lambda item: item[1], reverse=True)[:5]
        ]

        sales_by_category = self._group_sales_by_category(sales)

        # Pour le dashboard stock : chaque catégorie vendue expose aussi
        # les références produits associées. Cela permet au front d'afficher
        # une infobulle professionnelle au survol et de naviguer vers la liste
        # filtrée de la catégorie sans données statiques.
        category_products: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for pid, units in sales_by_product.items():
            product = product_lookup.get(pid) or {}
            category = product.get("categorie") or "Sans catégorie"
            category_products[category].append(
                {
                    "id": pid,
                    "sku": product.get("sku") or f"Produit {pid}",
                    "reference": product.get("sku") or f"Produit {pid}",
                    "name": product.get("nom") or f"Produit {pid}",
                    "units": safe_round(units, 0),
                }
            )

        for items in category_products.values():
            items.sort(key=lambda item: as_float(item.get("units")), reverse=True)

        top_categories_sold = [
            {
                **category,
                "products": category_products.get(category.get("categorie") or "Sans catégorie", [])[:12],
            }
            for category in sales_by_category[:5]
        ]

        critical_products: list[dict[str, Any]] = []
        slow_movers: list[dict[str, Any]] = []

        for product in products:
            status = self._stock_status(product)
            sold = sales_by_product.get(product.get("id"), 0.0)
            daily_sales = sold / period_days if period_days else 0
            product_coverage = as_float(product.get("stockDisponible")) / daily_sales if daily_sales else None
            seuil_min = product.get("seuilMin") if product.get("seuilMin") is not None else product.get("stockMinimum")
            quantite_a_commander = max(0.0, as_float(seuil_min) - as_float(product.get("stockDisponible"))) if seuil_min is not None else 0.0

            if status in {"rupture", "critique"}:
                critical_products.append(
                    {
                        "id": product.get("id"),
                        "sku": product.get("sku"),
                        "produit": product.get("nom"),
                        "categorie": product.get("categorie"),
                        "marque": product.get("marque"),
                        "stock": as_float(product.get("stockDisponible")),
                        "seuil_min": seuil_min,
                        "quantite_a_commander": safe_round(quantite_a_commander, 0),
                        "ventes_periode": safe_round(sold, 0),
                        "couverture_jours": safe_round(product_coverage, 1),
                        "statut": status,
                        "priority": "critique" if status == "rupture" else "haute",
                        "detail_url": f"/app/stock/products/{product.get('id')}",
                    }
                )

            if as_float(product.get("stockDisponible")) > 0:
                slow_score = as_float(product.get("stockDisponible")) / max(sold, 1)
                if sold <= 0 or slow_score >= 10:
                    slow_movers.append(
                        {
                            "id": product.get("id"),
                            "sku": product.get("sku"),
                            "produit": product.get("nom"),
                            "categorie": product.get("categorie") or "Sans catégorie",
                            "stock": as_float(product.get("stockDisponible")),
                            "ventes_periode": safe_round(sold, 0),
                            "slow_score": safe_round(slow_score, 2),
                            "couverture_jours": safe_round(product_coverage, 1),
                            "statut": "slow_mover",
                            "detail_url": f"/app/stock/products/{product.get('id')}",
                        }
                    )

        critical_products.sort(key=lambda item: (0 if item["statut"] == "rupture" else 1, -as_float(item.get("quantite_a_commander"))))
        slow_movers.sort(key=lambda item: (as_float(item.get("ventes_periode")), -as_float(item.get("stock"))))

        category_status = defaultdict(lambda: {"rupture": 0, "critique": 0, "normal": 0, "surstock": 0, "total": 0})
        category_restock = defaultdict(lambda: {"quantite_a_commander": 0.0, "produits_critiques": 0, "ruptures": 0})
        category_slow = defaultdict(lambda: {"produits": 0, "stock": 0.0, "ventes": 0.0})

        for product in products:
            category = product.get("categorie") or "Sans catégorie"
            status = self._stock_status(product)
            category_status[category][status] += 1
            category_status[category]["total"] += 1

        for item in critical_products:
            category = item.get("categorie") or "Sans catégorie"
            category_restock[category]["quantite_a_commander"] += as_float(item.get("quantite_a_commander"))
            category_restock[category]["produits_critiques"] += 1
            if item.get("statut") == "rupture":
                category_restock[category]["ruptures"] += 1

        for item in slow_movers:
            category = item.get("categorie") or "Sans catégorie"
            category_slow[category]["produits"] += 1
            category_slow[category]["stock"] += as_float(item.get("stock"))
            category_slow[category]["ventes"] += as_float(item.get("ventes_periode"))

        kpis = [
            self._kpi(
                "stock_levels",
                "Niveaux de stock",
                safe_round(current_stock_on_hand, 0),
                "u",
                "good" if current_stock_available > 0 else "danger",
                "Stock en main = stock disponible + stock réservé. Position actuelle et disponibilité.",
                delta=safe_round(available_rate, 1),
            ),
            self._kpi(
                "stock_efficiency",
                "Rotation du stock",
                safe_round(rotation, 0),
                "fois",
                "warning" if rotation is not None and rotation < 1 else "good",
                "Indique combien de fois le stock s’est renouvelé pendant la période sélectionnée. Plus la rotation est élevée, plus le stock circule efficacement.",
            ),
            self._kpi(
                "average_coverage",
                "Couverture moyenne",
                safe_round(coverage_days, 1),
                " j",
                "danger" if coverage_days is not None and coverage_days < 7 else ("warning" if coverage_days is not None and coverage_days < 30 else "good"),
                "Nombre de jours que le stock disponible peut couvrir selon les ventes moyennes journalières de la période.",
            ),
            self._kpi(
                "units_sold",
                "Unités vendues",
                safe_round(total_units, 0),
                " u",
                "good" if total_units > 0 else "neutral",
                "Total réel des unités vendues sur la période sélectionnée, calculé depuis la table des ventes.",
            ),
            self._kpi(
                "restock_priority",
                "Réappro. prioritaires",
                len(critical_products),
                "",
                "danger" if len(critical_products) else "good",
                "Nombre de produits à réapprovisionner en priorité : rupture ou stock disponible inférieur/égal au seuil minimum.",
            ),
        ]

        charts = {
            "stock_vs_sales": self._group_sales_by_day(sales),
            "top_categories_sold": top_categories_sold,
            "top_products_sold": top_products_sold,
            "top_products_slow_movers": slow_movers[:5],
            "top_categories_slow_movers": [
                {"categorie": key, "produits": val["produits"], "stock": safe_round(val["stock"], 0), "ventes": safe_round(val["ventes"], 0)}
                for key, val in sorted(category_slow.items(), key=lambda item: (item[1]["produits"], item[1]["stock"]), reverse=True)[:5]
            ],
            "stock_status_distribution": [
                {"name": "Rupture", "value": statuses["rupture"], "colorKey": "danger"},
                {"name": "Critique", "value": statuses["critique"], "colorKey": "warning"},
                {"name": "Normal", "value": statuses["normal"], "colorKey": "success"},
                {"name": "Surstock", "value": statuses["surstock"], "colorKey": "info"},
            ],
            "category_risk": [dict({"categorie": key}, **value) for key, value in sorted(category_status.items())],
            "sales_by_category": sales_by_category,
            "restock_by_category": [
                {
                    "categorie": key,
                    "quantite_a_commander": safe_round(value["quantite_a_commander"], 0),
                    "produits_critiques": value["produits_critiques"],
                    "ruptures": value["ruptures"],
                }
                for key, value in sorted(category_restock.items(), key=lambda item: item[1]["quantite_a_commander"], reverse=True)
                if value["quantite_a_commander"] > 0 or value["produits_critiques"] > 0
            ],
        }

        insights = [
            {
                "type": "stock",
                "status": "danger" if statuses["rupture"] else "good",
                "title": "Ruptures à traiter",
                "message": f"{statuses['rupture']} produit(s) en rupture et {statuses['critique']} produit(s) critiques sur la période réelle de la base.",
            },
            {
                "type": "data",
                "status": "warning" if sales_source == "none" else "good",
                "title": "Fiabilité des données",
                "message": f"Source utilisée : {sales_source}. Période ancrée sur la dernière date disponible en base.",
            },
        ]

        warnings = list(data_warnings)
        if avg_stock_historical is None:
            warnings.append("Stock moyen historique indisponible : la rotation utilise le stock actuel moyen en fallback.")

        tables = {
            "critical_products": critical_products[:12],
            "restock_priorities": critical_products[:10],
            "slow_movers": slow_movers[:10],
        }

        return self._contract(f, kpis, charts, tables, insights, warnings)

    # ======================================================
    # Dashboard Pricing
    # ======================================================

    def pricing_dashboard(self, params: dict[str, Any]) -> dict[str, Any]:
        f, products, sales_source, sales, promos, market, data_warnings = self._base(params)

        total_products = len(products)
        by_id = {p["id"]: p for p in products if p.get("id") is not None}

        margins = [self._margin_pct(product) for product in products]
        margins = [m for m in margins if m is not None]
        avg_margin = mean(margins) if margins else None

        reliable_ids = [
            p["id"]
            for p in products
            if p.get("id") in market and market[p["id"]].get("count", 0) > 0
        ]

        positions = defaultdict(int)
        category_positions = defaultdict(
            lambda: {
                "sous_marche": 0,
                "aligne": 0,
                "au_dessus": 0,
            }
        )

        gaps: list[float] = []
        products_to_correct: list[dict[str, Any]] = []
        products_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for product in products:
            item = market.get(product.get("id"))
            position = self._market_position(product, item)

            if not position or not item or not item.get("avg_price"):
                continue

            category = product.get("categorie") or "Sans catégorie"

            positions[position] += 1
            category_positions[category][position] += 1

            gap = (
                (as_float(product.get("prixVente")) - as_float(item["avg_price"]))
                / as_float(item["avg_price"])
            ) * 100

            gaps.append(gap)

            product_light = {
                "id": product.get("id"),
                "sku": product.get("sku") or f"Produit {product.get('id')}",
                "reference": product.get("sku") or f"Produit {product.get('id')}",
                "name": product.get("nom") or product.get("sku") or f"Produit {product.get('id')}",
                "gap": safe_round(gap, 2),
                "position": position,
                "prix_actuel": product.get("prixVente"),
                "prix_concurrent_moyen": safe_round(item["avg_price"], 2),
            }
            products_by_category[category].append(product_light)

            if abs(gap) >= 5:
                decision = {
                    "sous_marche": "prix potentiellement trop bas par rapport au marché",
                    "au_dessus": "prix potentiellement trop haut par rapport au marché",
                    "aligne": "prix proche du marché",
                }.get(position, "prix à vérifier")

                products_to_correct.append(
                    {
                        "id": product.get("id"),
                        "sku": product.get("sku"),
                        "produit": product.get("nom"),
                        "categorie": category,
                        "marque": product.get("marque"),
                        "prix_actuel": product.get("prixVente"),
                        "prix_concurrent_moyen": safe_round(item["avg_price"], 2),
                        "prix_concurrent_min": safe_round(item.get("min_price"), 2),
                        "prix_concurrent_max": safe_round(item.get("max_price"), 2),
                        "nb_concurrents": item.get("count", 0),
                        "ecart_pct": safe_round(gap, 2),
                        "position": position,
                        "marge_pct": safe_round(self._margin_pct(product), 2),
                        "why": (
                            f"Ce produit est à revoir car son écart marché est de {safe_round(gap, 2)}%. "
                            f"Position : {decision}. "
                            f"Prix actuel = {product.get('prixVente')}, "
                            f"prix concurrent moyen = {safe_round(item['avg_price'], 2)}."
                        ),
                        "detail_url": f"/app/pricing/products/{product.get('id')}",
                    }
                )

        products_to_correct.sort(
            key=lambda item: abs(item.get("ecart_pct") or 0),
            reverse=True,
        )

        # ==================================================
        # Ventes, profit et catégories
        # ==================================================

        estimated_profit = 0.0

        category_sales = defaultdict(
            lambda: {
                "units": 0.0,
                "revenue": 0.0,
                "profit": 0.0,
            }
        )
        category_sold_products: dict[str, dict[Any, dict[str, Any]]] = defaultdict(dict)

        profit_by_day = defaultdict(float)
        revenue_by_day = defaultdict(float)
        gap_by_day = defaultdict(lambda: {"sum": 0.0, "count": 0})

        for row in sales:
            product = by_id.get(row.get("product_id"))
            category = (
                row.get("categorie")
                or (product.get("categorie") if product else None)
                or "Sans catégorie"
            )
            units = as_float(row.get("units"))
            revenue = as_float(row.get("revenue"))
            sale_price = as_float(row.get("price"), as_float(product.get("prixVente") if product else 0))

            profit = 0.0
            if product and product.get("prixCout") is not None:
                profit = (sale_price - as_float(product.get("prixCout"))) * units
                estimated_profit += profit

            category_sales[category]["units"] += units
            category_sales[category]["revenue"] += revenue
            category_sales[category]["profit"] += profit

            product_key = row.get("product_id") or row.get("sku") or f"{category}-{len(category_sold_products[category])}"
            if product_key not in category_sold_products[category]:
                category_sold_products[category][product_key] = {
                    "id": row.get("product_id"),
                    "sku": row.get("sku") or (product.get("sku") if product else None) or f"Produit {product_key}",
                    "reference": row.get("sku") or (product.get("sku") if product else None) or f"Produit {product_key}",
                    "name": product.get("nom") if product else row.get("sku") or f"Produit {product_key}",
                    "units": 0.0,
                    "profit": 0.0,
                }

            category_sold_products[category][product_key]["units"] += units
            category_sold_products[category][product_key]["profit"] += profit

            day = iso(row.get("date"))
            if day:
                profit_by_day[day] += profit
                revenue_by_day[day] += revenue

                item = market.get(row.get("product_id"))
                if item and item.get("avg_price"):
                    gap = ((sale_price - as_float(item["avg_price"])) / as_float(item["avg_price"])) * 100
                    gap_by_day[day]["sum"] += gap
                    gap_by_day[day]["count"] += 1

        for category, items in category_sold_products.items():
            for item in items.values():
                item["units"] = safe_round(item.get("units"), 0)
                item["profit"] = safe_round(item.get("profit"), 2)

        def category_products_payload(category: str) -> list[dict[str, Any]]:
            products_map = category_sold_products.get(category) or {}
            sold_payload = sorted(
                products_map.values(),
                key=lambda item: as_float(item.get("units")),
                reverse=True,
            )

            if sold_payload:
                return sold_payload[:12]

            fallback = products_by_category.get(category, [])
            return fallback[:12]

        categories_sorted_by_sales = sorted(
            category_sales.items(),
            key=lambda item: item[1]["units"],
            reverse=True,
        )

        all_categories_positioning = []
        for category, values in categories_sorted_by_sales:
            pos = category_positions.get(category, {})
            all_categories_positioning.append(
                {
                    "categorie": category,
                    "units_sold": safe_round(values.get("units"), 0),
                    "revenue": safe_round(values.get("revenue"), 2),
                    "profit": safe_round(values.get("profit"), 2),
                    "sous_marche": as_int(pos.get("sous_marche", 0)),
                    "aligne": as_int(pos.get("aligne", 0)),
                    "au_dessus": as_int(pos.get("au_dessus", 0)),
                    "products": category_products_payload(category),
                }
            )

        top_sold_categories_positioning = all_categories_positioning

        categories_vs_sales = [
            {
                "name": category,
                "categorie": category,
                "value": safe_round(values.get("units"), 0),
                "revenue": safe_round(values.get("revenue"), 2),
                "products": category_products_payload(category),
            }
            for category, values in categories_sorted_by_sales[:6]
            if as_float(values.get("units")) > 0
        ]

        categories_vs_profit = [
            {
                "name": category,
                "categorie": category,
                "value": safe_round(values.get("profit"), 2),
                "units": safe_round(values.get("units"), 0),
                "products": category_products_payload(category),
            }
            for category, values in sorted(
                category_sales.items(),
                key=lambda item: item[1]["profit"],
                reverse=True,
            )[:6]
            if as_float(values.get("profit")) != 0
        ]

        all_timeline_days = sorted(set(profit_by_day.keys()) | set(revenue_by_day.keys()))
        profit_timeline = [
            {
                "date": day,
                "revenue": safe_round(revenue_by_day.get(day, 0.0), 2),
                "profit": safe_round(profit_by_day.get(day, 0.0), 2),
            }
            for day in all_timeline_days
        ]

        market_gap_timeline = [
            {
                "date": day,
                "market_gap": safe_round(value["sum"] / value["count"], 2) if value["count"] else 0,
            }
            for day, value in sorted(gap_by_day.items())
        ]

        discount_by_category = defaultdict(
            lambda: {
                "count": 0,
                "discount_sum": 0.0,
            }
        )

        for product in products:
            promo = promos.get(product.get("id"))

            if not promo:
                continue

            category = product.get("categorie") or "Sans catégorie"
            discount_by_category[category]["count"] += 1

            promo_price = promo.get("prix_promo")

            if promo_price and product.get("prixVente"):
                discount_by_category[category]["discount_sum"] += max(
                    0,
                    (
                        as_float(product.get("prixVente"))
                        - as_float(promo_price)
                    )
                    / as_float(product.get("prixVente"))
                    * 100,
                )

        product_names = {
            p["id"]: p.get("nom")
            for p in products
            if p.get("id") is not None
        }

        promo_table = [
            {
                "product_id": product_id,
                "produit": product_names.get(product_id),
                "promotion": promo.get("nom"),
                "type": promo.get("type"),
                "valeur": promo.get("valeur"),
                "prix_promo": promo.get("prix_promo"),
                "date_fin": promo.get("date_fin"),
                "why": "Promotion active à la date de fin de période du dashboard.",
            }
            for product_id, promo in promos.items()
            if product_id in product_names
        ]

        warnings = list(data_warnings)

        if not reliable_ids:
            warnings.append(
                "Aucune donnée concurrente fiable trouvée : les KPI de positionnement marché "
                "ne sont pas encore exploitables."
            )

        if not margins:
            warnings.append(
                "Prix coût ou prix vente manquant : marge moyenne/profit estimé incomplets."
            )

        avg_gap = safe_round(mean(gaps), 2) if gaps else None

        kpis = [
            self._kpi(
                "avg_margin",
                "Marge moyenne",
                safe_round(avg_margin, 2),
                "%",
                "good" if avg_margin is not None and avg_margin >= 20 else "warning",
                "Marge moyenne réalisée sur les produits suivis.",
            ),
            self._kpi(
                "promo_rate",
                "Produits en promotion",
                pct(len(promos), total_products),
                "%",
                "neutral",
                "Part des produits actuellement liés à une promotion active.",
            ),
            self._kpi(
                "market_gap",
                "Écart moyen marché",
                avg_gap,
                "%",
                "warning" if avg_gap and abs(avg_gap) >= 5 else "neutral",
                "Écart moyen entre notre prix et le prix concurrent moyen.",
                trend="down" if avg_gap and avg_gap < 0 else ("up" if avg_gap and avg_gap > 0 else "stable"),
            ),
            self._kpi(
                "under_market",
                "Sous marché",
                positions["sous_marche"],
                "produits",
                "warning" if positions["sous_marche"] else "good",
                "Produits vendus sous le niveau moyen du marché.",
            ),
            self._kpi(
                "over_market",
                "Au-dessus marché",
                positions["au_dessus"],
                "produits",
                "warning" if positions["au_dessus"] else "good",
                "Produits vendus au-dessus du niveau moyen du marché.",
            ),
            self._kpi(
                "estimated_profit",
                "Profit estimé",
                safe_round(estimated_profit, 2),
                "TND",
                "neutral",
                f"Profit estimé sur les ventes source {sales_source}.",
            ),
        ]

        charts = {
            "all_categories_positioning": all_categories_positioning,
            "top_sold_categories_positioning": top_sold_categories_positioning,
            "categories_vs_sales": categories_vs_sales,
            "categories_vs_profit": categories_vs_profit,
            "profit_timeline": profit_timeline,
            "market_gap_timeline": market_gap_timeline,

            # Anciennes clés conservées pour éviter de casser les autres écrans/export.
            "market_position_by_category": [
                dict(
                    {
                        "categorie": key,
                        "products": products_by_category.get(key, [])[:12],
                    },
                    **value,
                )
                for key, value in sorted(category_positions.items())
            ],
            "price_evolution": self._price_evolution(sales, market),
            "discount_by_category": [
                {
                    "categorie": key,
                    "produits": value["count"],
                    "remise_moyenne": (
                        safe_round(value["discount_sum"] / value["count"], 2)
                        if value["count"]
                        else 0
                    ),
                    "products": category_products_payload(key),
                }
                for key, value in sorted(
                    discount_by_category.items(),
                    key=lambda item: item[1]["count"],
                    reverse=True,
                )
            ],
            "recommendation_distribution": [
                {"name": "Hausse", "value": positions["sous_marche"], "colorKey": "success"},
                {"name": "Stable", "value": positions["aligne"], "colorKey": "neutral"},
                {"name": "Baisse", "value": positions["au_dessus"], "colorKey": "warning"},
            ],
        }

        insights = [
            {
                "type": "pricing",
                "status": "warning" if products_to_correct else "good",
                "title": "Produits à revoir",
                "message": (
                    f"{len(products_to_correct)} produit(s) ont un écart marché "
                    "supérieur ou égal à 5%."
                ),
            },
            {
                "type": "data",
                "status": "warning" if not reliable_ids else "good",
                "title": "Données concurrentes",
                "message": f"{len(reliable_ids)} produit(s) avec prix concurrents fiables.",
            },
        ]

        tables = {
            "products_to_correct": products_to_correct[:15],
            "active_promotions": promo_table[:15],
            "competitor_sources": self._latest_competitor_sources(),
        }

        return self._contract(f, kpis, charts, tables, insights, warnings)

    # ======================================================
    # Dashboard Manager
    # ======================================================

    def manager_dashboard(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Dashboard Manager = fusion réelle Stock + Pricing.
        Aucune donnée statique : tout est recalculé depuis products, sales/history,
        promotions actives et produits concurrents disponibles dans la base.
        """
        f, products, sales_source, sales, promos, market, data_warnings = self._base(params)

        period_days = as_int(f.get("period_days"), 30) or 30
        total_products = len(products)
        by_id = {p["id"]: p for p in products if p.get("id") is not None}

        # ==================================================
        # Stock : état global + risques
        # ==================================================
        statuses = defaultdict(int)
        current_stock_available = 0.0
        for product in products:
            statuses[self._stock_status(product)] += 1
            current_stock_available += as_float(product.get("stockDisponible"))

        sales_by_product = defaultdict(float)
        revenue_by_product = defaultdict(float)
        for row in sales:
            pid = row.get("product_id")
            if pid is not None:
                sales_by_product[pid] += as_float(row.get("units"))
                revenue_by_product[pid] += as_float(row.get("revenue"))

        total_units = sum(as_float(row.get("units")) for row in sales)
        revenue = sum(as_float(row.get("revenue")) for row in sales)
        avg_daily_sales = total_units / period_days if period_days else 0
        stock_coverage = current_stock_available / avg_daily_sales if avg_daily_sales else None

        stock_risks: list[dict[str, Any]] = []
        for product in products:
            status = self._stock_status(product)
            if status not in {"rupture", "critique"}:
                continue

            sold = sales_by_product.get(product.get("id"), 0.0)
            seuil_min = (
                product.get("seuilMin")
                if product.get("seuilMin") is not None
                else product.get("stockMinimum")
            )

            stock_risks.append(
                {
                    "id": product.get("id"),
                    "sku": product.get("sku"),
                    "produit": product.get("nom"),
                    "categorie": product.get("categorie") or "Sans catégorie",
                    "statut": status,
                    "stock": safe_round(as_float(product.get("stockDisponible")), 0),
                    "seuil_min": seuil_min,
                    "ventes_periode": safe_round(sold, 0),
                    "why": (
                        f"Stock actuel = {safe_round(as_float(product.get('stockDisponible')), 0)}, "
                        f"seuil minimum = {seuil_min}, ventes période = {safe_round(sold, 0)}."
                    ),
                    "detail_url": f"/app/stock/products/{product.get('id')}",
                    "priority_family": "Stock",
                    "priority_score": 100 if status == "rupture" else 80,
                }
            )

        stock_risks.sort(
            key=lambda item: (
                0 if item.get("statut") == "rupture" else 1,
                -as_float(item.get("ventes_periode")),
            )
        )

        # ==================================================
        # Pricing : couverture marché + écarts à traiter
        # ==================================================
        market_covered = 0
        market_positions = defaultdict(int)
        market_gap_by_category = defaultdict(lambda: {"sum": 0.0, "count": 0})
        pricing_risks: list[dict[str, Any]] = []
        all_market_gaps: list[float] = []

        for product in products:
            product_id = product.get("id")
            item = market.get(product_id)

            if not item or not item.get("avg_price"):
                continue

            market_covered += 1
            position = self._market_position(product, item)
            if position:
                market_positions[position] += 1

            avg_price = as_float(item.get("avg_price"))
            current_price = as_float(product.get("prixVente"))
            if not avg_price:
                continue

            gap = ((current_price - avg_price) / avg_price) * 100
            all_market_gaps.append(gap)

            category = product.get("categorie") or "Sans catégorie"
            market_gap_by_category[category]["sum"] += gap
            market_gap_by_category[category]["count"] += 1

            if abs(gap) >= 5:
                margin_pct = self._margin_pct(product)
                pricing_risks.append(
                    {
                        "id": product_id,
                        "sku": product.get("sku"),
                        "produit": product.get("nom"),
                        "categorie": category,
                        "prix_actuel": safe_round(current_price, 2),
                        "prix_concurrent_moyen": safe_round(avg_price, 2),
                        "ecart_pct": safe_round(gap, 2),
                        "marge_pct": safe_round(margin_pct, 2),
                        "position": position or "à vérifier",
                        "nb_concurrents": item.get("count", 0),
                        "why": (
                            f"Écart marché = {safe_round(gap, 2)}%. "
                            f"Prix actuel = {safe_round(current_price, 2)}, "
                            f"prix concurrent moyen = {safe_round(avg_price, 2)}."
                        ),
                        "detail_url": f"/app/pricing/products/{product_id}",
                        "priority_family": "Pricing",
                        "priority_score": abs(gap),
                    }
                )

        pricing_risks.sort(key=lambda item: abs(as_float(item.get("ecart_pct"))), reverse=True)

        promo_count = len([p for p in products if p.get("id") in promos])
        avg_market_gap = mean(all_market_gaps) if all_market_gaps else None

        # ==================================================
        # Finance réelle : CA / profit / catégories
        # ==================================================
        estimated_profit = 0.0
        category_finance = defaultdict(
            lambda: {
                "units": 0.0,
                "revenue": 0.0,
                "profit": 0.0,
            }
        )
        profit_by_day = defaultdict(float)
        revenue_by_day = defaultdict(float)
        category_sold_products: dict[str, dict[Any, dict[str, Any]]] = defaultdict(dict)
        gap_by_day = defaultdict(lambda: {"sum": 0.0, "count": 0})

        for row in sales:
            product = by_id.get(row.get("product_id"))
            category = (
                row.get("categorie")
                or (product.get("categorie") if product else None)
                or "Sans catégorie"
            )
            units = as_float(row.get("units"))
            revenue_row = as_float(row.get("revenue"))
            sale_price = as_float(row.get("price"), as_float(product.get("prixVente") if product else 0))

            profit_row = 0.0
            if product and product.get("prixCout") is not None:
                profit_row = (sale_price - as_float(product.get("prixCout"))) * units
                estimated_profit += profit_row

            day = iso(row.get("date"))
            if day:
                profit_by_day[day] += profit_row
                revenue_by_day[day] += revenue_row

            category_finance[category]["units"] += units
            category_finance[category]["revenue"] += revenue_row
            category_finance[category]["profit"] += profit_row

            product_key = row.get("product_id") or row.get("sku") or f"{category}-{len(category_sold_products[category])}"
            if product_key not in category_sold_products[category]:
                category_sold_products[category][product_key] = {
                    "id": row.get("product_id"),
                    "sku": row.get("sku") or (product.get("sku") if product else None) or f"Produit {product_key}",
                    "reference": row.get("sku") or (product.get("sku") if product else None) or f"Produit {product_key}",
                    "name": product.get("nom") if product else row.get("sku") or f"Produit {product_key}",
                    "units": 0.0,
                    "profit": 0.0,
                }
            category_sold_products[category][product_key]["units"] += units
            category_sold_products[category][product_key]["profit"] += profit_row

            item = market.get(row.get("product_id"))
            if day and item and item.get("avg_price"):
                denominator = as_float(item.get("avg_price"))
                if denominator:
                    daily_gap = ((sale_price - denominator) / denominator) * 100
                    gap_by_day[day]["sum"] += daily_gap
                    gap_by_day[day]["count"] += 1

        finance_by_category = [
            {
                "categorie": key,
                "units": safe_round(value["units"], 0),
                "revenue": safe_round(value["revenue"], 2),
                "profit": safe_round(value["profit"], 2),
            }
            for key, value in sorted(
                category_finance.items(),
                key=lambda item: item[1]["revenue"],
                reverse=True,
            )
        ]

        for category, items in category_sold_products.items():
            for item in items.values():
                item["units"] = safe_round(item.get("units"), 0)
                item["profit"] = safe_round(item.get("profit"), 2)

        def category_products_payload(category: str) -> list[dict[str, Any]]:
            products_map = category_sold_products.get(category) or {}
            return sorted(
                products_map.values(),
                key=lambda item: as_float(item.get("units")),
                reverse=True,
            )[:12]

        top_categories_sold = [
            {
                "name": row["categorie"],
                "categorie": row["categorie"],
                "units": row["units"],
                "value": row["units"],
                "revenue": row["revenue"],
                "profit": row["profit"],
                "products": category_products_payload(row["categorie"]),
            }
            for row in finance_by_category[:5]
            if as_float(row.get("units")) > 0
        ]

        category_slow = defaultdict(lambda: {"produits": 0, "stock": 0.0, "ventes": 0.0})
        for product in products:
            stock_value = as_float(product.get("stockDisponible"))
            sold_value = as_float(sales_by_product.get(product.get("id"), 0.0))
            if stock_value <= 0:
                continue
            if sold_value > 2:
                continue
            category = product.get("categorie") or "Sans catégorie"
            category_slow[category]["produits"] += 1
            category_slow[category]["stock"] += stock_value
            category_slow[category]["ventes"] += sold_value

        top_categories_slow_movers = [
            {
                "name": key,
                "categorie": key,
                "value": safe_round(value["stock"], 0),
                "stock": safe_round(value["stock"], 0),
                "produits": value["produits"],
                "ventes": safe_round(value["ventes"], 0),
            }
            for key, value in sorted(category_slow.items(), key=lambda item: (item[1]["stock"], item[1]["produits"]), reverse=True)[:5]
        ]

        all_timeline_days = sorted(set(profit_by_day.keys()) | set(revenue_by_day.keys()))
        profit_timeline = [
            {
                "date": day,
                "revenue": safe_round(revenue_by_day.get(day, 0.0), 2),
                "profit": safe_round(profit_by_day.get(day, 0.0), 2),
            }
            for day in all_timeline_days
        ]

        market_gap_timeline = [
            {
                "date": day,
                "market_gap": safe_round(value["sum"] / value["count"], 2) if value["count"] else 0,
            }
            for day, value in sorted(gap_by_day.items())
        ]

        market_gap_categories = [
            {
                "categorie": category,
                "ecart_pct": safe_round(values["sum"] / values["count"], 2) if values["count"] else 0,
                "produits": values["count"],
            }
            for category, values in sorted(
                market_gap_by_category.items(),
                key=lambda item: abs(item[1]["sum"] / item[1]["count"]) if item[1]["count"] else 0,
                reverse=True,
            )
        ]

        manager_priorities = [
            {
                **item,
                "type": "Stock",
                "urgence": "critique" if item.get("statut") == "rupture" else "haute",
            }
            for item in stock_risks[:8]
        ] + [
            {
                **item,
                "type": "Pricing",
                "urgence": "haute" if abs(as_float(item.get("ecart_pct"))) >= 15 else "moyenne",
            }
            for item in pricing_risks[:8]
        ]

        manager_priorities.sort(
            key=lambda item: (
                0 if item.get("urgence") == "critique" else 1 if item.get("urgence") == "haute" else 2,
                -as_float(item.get("priority_score")),
            )
        )

        stock_risk_count = statuses["rupture"] + statuses["critique"]
        pricing_risk_count = len(pricing_risks)

        kpis = [
            self._kpi(
                "revenue",
                "Chiffre d’affaire",
                safe_round(revenue, 2),
                "TND",
                "neutral",
                f"Chiffre d’affaires calculé depuis {sales_source}, sur la période sélectionnée.",
            ),
            self._kpi(
                "estimated_profit",
                "Profit estimé",
                safe_round(estimated_profit, 2),
                "TND",
                "neutral",
                "Profit estimé = somme((prix de vente réel - prix de coût) × unités vendues).",
            ),
            self._kpi(
                "products_tracked",
                "Produits suivis",
                total_products,
                "",
                "neutral",
                "Nombre de produits suivis dans le périmètre manager selon les filtres appliqués.",
            ),
            self._kpi(
                "units_sold",
                "Unités vendues",
                safe_round(total_units, 0),
                "",
                "neutral",
                "Volume total vendu sur la période sélectionnée.",
            ),
            self._kpi(
                "stock_risk",
                "Risques stock",
                stock_risk_count,
                "",
                "danger" if statuses["rupture"] else "warning" if statuses["critique"] else "good",
                "Nombre de produits en rupture ou en stock critique.",
            ),
            self._kpi(
                "pricing_risk",
                "Risques pricing",
                pricing_risk_count,
                "",
                "warning" if pricing_risk_count else "good",
                "Produits avec un écart marché significatif, calculé à partir des prix concurrents collectés.",
            ),
            self._kpi(
                "market_coverage",
                "Couverture marché",
                pct(market_covered, total_products),
                "%",
                "good" if market_covered else "warning",
                "Part des produits disposant d’au moins un prix concurrent exploitable.",
            ),
            self._kpi(
                "promo_rate",
                "Taux promotion",
                pct(promo_count, total_products),
                "%",
                "neutral",
                "Part des produits actuellement associés à une promotion active.",
            ),
            self._kpi(
                "stock_coverage",
                "Couverture stock",
                safe_round(stock_coverage, 1),
                "j",
                "warning" if stock_coverage is not None and stock_coverage < 7 else "neutral",
                "Nombre moyen de jours couverts par le stock actuel selon les ventes de la période.",
            ),
        ]

        charts = {
            "finance_by_category": finance_by_category[:10],
            "top_categories_sold": top_categories_sold,
            "top_categories_slow_movers": top_categories_slow_movers,
            "profit_timeline": profit_timeline,
            "market_gap_timeline": market_gap_timeline,
            "stock_status_distribution": [
                {"name": "Rupture", "value": statuses["rupture"], "colorKey": "danger"},
                {"name": "Critique", "value": statuses["critique"], "colorKey": "warning"},
                {"name": "Normal", "value": statuses["normal"], "colorKey": "success"},
                {"name": "Surstock", "value": statuses["surstock"], "colorKey": "info"},
            ],
            "sales_trend": [
                {**row, "profit": safe_round(profit_by_day.get(row.get("date"), 0.0), 2)}
                for row in self._group_sales_by_day(sales)
            ],
            "market_position_distribution": [
                {"name": "Sous marché", "value": market_positions["sous_marche"], "colorKey": "info"},
                {"name": "Aligné", "value": market_positions["aligne"], "colorKey": "success"},
                {"name": "Au-dessus", "value": market_positions["au_dessus"], "colorKey": "warning"},
            ],
            "market_gap_by_category": market_gap_categories[:8],
            "priority_mix": [
                {"name": "Stock", "value": stock_risk_count, "colorKey": "warning"},
                {"name": "Pricing", "value": pricing_risk_count, "colorKey": "info"},
            ],
        }

        tables = {
            "top_categories": finance_by_category[:10],
            "stock_risks": stock_risks[:12],
            "pricing_risks": pricing_risks[:12],
            "manager_priorities": manager_priorities[:12],
        }

        warnings = list(data_warnings)
        insights = [
            {
                "title": "Lecture manager",
                "message": (
                    f"{stock_risk_count} risque(s) stock et {pricing_risk_count} risque(s) pricing "
                    "sont consolidés dans les priorités à traiter."
                ),
                "severity": "info",
            }
        ]

        if avg_market_gap is not None:
            insights.append(
                {
                    "title": "Position marché",
                    "message": f"Écart marché moyen observé : {safe_round(avg_market_gap, 2)}%.",
                    "severity": "info",
                }
            )

        return self._contract(f, kpis, charts, tables, insights, warnings)
