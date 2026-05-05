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
                .filter(SalesHistory.product_id.in_(skus))
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
        warnings: list[str] = []
        rows: list[dict[str, Any]] = []

        product_ids = [p["id"] for p in products if p.get("id") is not None]
        by_id = {p["id"]: p for p in products if p.get("id") is not None}

        skus = [p["sku"] for p in products if p.get("sku")]
        by_sku = {p["sku"]: p for p in products if p.get("sku")}

        start_dt = datetime.combine(filters["start_date"], time.min)
        end_dt = datetime.combine(filters["end_date"], time.max)

        stock_by_sku_day: dict[tuple[str, date], float] = {}

        if skus:
            stock_rows = (
                self.db.query(
                    SalesHistory.product_id.label("product_id"),
                    SalesHistory.date.label("date"),
                    func.avg(SalesHistory.stock).label("avg_stock"),
                )
                .filter(SalesHistory.product_id.in_(skus))
                .filter(SalesHistory.date >= filters["start_date"])
                .filter(SalesHistory.date <= filters["end_date"])
                .filter(SalesHistory.stock.isnot(None))
                .group_by(SalesHistory.product_id, SalesHistory.date)
                .all()
            )

            stock_by_sku_day = {
                (row.product_id, row.date): as_float(row.avg_stock)
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
            if not any(r.get("stock_snapshot") is not None for r in rows):
                warnings.append(
                    "Les ventes viennent de ventes/lignes_ventes, mais aucun stock historique "
                    "n'a été trouvé dans historique_ventes.stock pour stock_vs_sales. "
                    "Le graphique affiche stock_avg = null au lieu d'utiliser un faux stock actuel."
                )

            return "ventes", rows, warnings

        if not skus:
            return "none", [], [
                "Aucun SKU produit disponible pour chercher les ventes historiques."
            ]

        history_rows = (
            self.db.query(
                SalesHistory.date.label("date"),
                SalesHistory.product_id.label("product_id"),
                SalesHistory.category.label("category"),
                SalesHistory.sales.label("sales"),
                SalesHistory.price.label("price"),
                SalesHistory.stock.label("stock"),
            )
            .filter(SalesHistory.product_id.in_(skus))
            .filter(SalesHistory.date >= filters["start_date"])
            .filter(SalesHistory.date <= filters["end_date"])
            .all()
        )

        for row in history_rows:
            product = by_sku.get(row.product_id)

            quantity = as_float(row.sales)
            fallback_price = product.get("prixVente") if product else 0
            price = as_float(row.price, as_float(fallback_price))

            rows.append(
                {
                    "date": row.date,
                    "product_id": product.get("id") if product else None,
                    "sku": row.product_id,
                    "categorie": (
                        row.category
                        or (product.get("categorie") if product else None)
                        or "Sans catégorie"
                    ),
                    "units": quantity,
                    "revenue": quantity * price,
                    "price": price,
                    "source": "historique_ventes",
                    "stock_snapshot": as_float(row.stock) if row.stock is not None else None,
                }
            )

        if not rows:
            warnings.append(
                "Aucune vente trouvée dans ventes/lignes_ventes ni dans historique_ventes "
                "sur la période calculée."
            )

        return ("historique_ventes" if rows else "none"), rows, warnings

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

        statuses = defaultdict(int)
        for product in products:
            statuses[self._stock_status(product)] += 1

        total_units = sum(as_float(row.get("units")) for row in sales)
        revenue = sum(as_float(row.get("revenue")) for row in sales)

        avg_daily_sales = total_units / f["period_days"] if f.get("period_days") else None

        avg_stock_historical = self._avg_historical_stock(sales)
        current_stock_total = sum(as_float(p.get("stockDisponible")) for p in products)

        current_avg_stock = (
            mean([as_float(p.get("stockDisponible")) for p in products])
            if products
            else None
        )

        stock_reference = (
            avg_stock_historical
            if avg_stock_historical is not None
            else current_avg_stock
        )

        rotation = (total_units / stock_reference) if stock_reference else None
        coverage = (current_stock_total / avg_daily_sales) if avg_daily_sales else None

        warnings = list(data_warnings)

        if avg_stock_historical is None:
            warnings.append(
                "Stock moyen historique indisponible : la rotation utilise le stock actuel moyen "
                "en fallback. Pour une rotation 100% fiable, importer historique_ventes.stock."
            )

        sales_by_product = defaultdict(float)

        for row in sales:
            if row.get("product_id"):
                sales_by_product[row["product_id"]] += as_float(row.get("units"))

        critical_products: list[dict[str, Any]] = []
        slow_movers: list[dict[str, Any]] = []

        for product in products:
            status = self._stock_status(product)
            sold = sales_by_product.get(product.get("id"), 0.0)
            daily_sales = sold / f["period_days"] if f.get("period_days") else 0

            product_coverage = (
                as_float(product.get("stockDisponible")) / daily_sales
                if daily_sales
                else None
            )

            seuil_min = (
                product.get("seuilMin")
                if product.get("seuilMin") is not None
                else product.get("stockMinimum")
            )

            quantite_a_commander = max(
                0.0,
                as_float(seuil_min) - as_float(product.get("stockDisponible")),
            ) if seuil_min is not None else 0.0

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
                        "ventes_periode": round(sold, 2),
                        "couverture_jours": safe_round(product_coverage, 1),
                        "statut": status,
                        "priority": "critique" if status == "rupture" else "haute",
                        "why": (
                            f"Ce produit est prioritaire car stock actuel = {product.get('stockDisponible') or 0}, "
                            f"ventes sur {f['period_days']} jours = {round(sold, 2)}, "
                            f"couverture = {safe_round(product_coverage, 1) if product_coverage is not None else 0} jour(s), "
                            f"seuil min = {seuil_min}."
                        ),
                        "detail_url": f"/app/stock/products/{product.get('id')}",
                    }
                )

            if sold <= 0 and as_float(product.get("stockDisponible")) > 0:
                slow_movers.append(
                    {
                        "id": product.get("id"),
                        "sku": product.get("sku"),
                        "produit": product.get("nom"),
                        "categorie": product.get("categorie"),
                        "stock": as_float(product.get("stockDisponible")),
                        "ventes_periode": round(sold, 2),
                        "statut": "slow_mover",
                        "why": (
                            f"Ce produit a du stock ({product.get('stockDisponible') or 0}) "
                            f"mais aucune vente sur {f['period_days']} jours."
                        ),
                        "detail_url": f"/app/stock/products/{product.get('id')}",
                    }
                )

        critical_products.sort(
            key=lambda item: (
                0 if item["statut"] == "rupture" else 1,
                -(as_float(item.get("quantite_a_commander"))),
                item["couverture_jours"]
                if item["couverture_jours"] is not None
                else 999999,
            )
        )

        category_restock = defaultdict(
            lambda: {
                "quantite_a_commander": 0.0,
                "produits_critiques": 0,
                "ruptures": 0,
            }
        )

        for item in critical_products:
            category = item.get("categorie") or "Sans catégorie"
            category_restock[category]["quantite_a_commander"] += as_float(item.get("quantite_a_commander"))
            category_restock[category]["produits_critiques"] += 1
            if item.get("statut") == "rupture":
                category_restock[category]["ruptures"] += 1

        category_status = defaultdict(
            lambda: {
                "rupture": 0,
                "critique": 0,
                "normal": 0,
                "surstock": 0,
                "total": 0,
            }
        )
        category_coverage = defaultdict(
            lambda: {
                "coverage_sum": 0.0,
                "coverage_count": 0,
                "products": 0,
                "risk_products": 0,
            }
        )

        for product in products:
            category = product.get("categorie") or "Sans catégorie"
            status = self._stock_status(product)
            sold = sales_by_product.get(product.get("id"), 0.0)
            daily_sales = sold / f["period_days"] if f.get("period_days") else 0
            product_coverage = (
                as_float(product.get("stockDisponible")) / daily_sales
                if daily_sales > 0
                else None
            )

            category_status[category][status] += 1
            category_status[category]["total"] += 1
            category_coverage[category]["products"] += 1

            if status in {"rupture", "critique"}:
                category_coverage[category]["risk_products"] += 1

            if product_coverage is not None:
                category_coverage[category]["coverage_sum"] += product_coverage
                category_coverage[category]["coverage_count"] += 1

        kpis = [
            self._kpi(
                "total_products",
                "Total produits",
                total_products,
                description="Nombre de produits selon les filtres.",
            ),
            self._kpi(
                "rupture_rate",
                "Taux rupture",
                pct(statuses["rupture"], total_products),
                "%",
                "danger" if statuses["rupture"] else "good",
                "Produits avec stock disponible <= 0.",
            ),
            self._kpi(
                "critical_rate",
                "Taux critique",
                pct(statuses["critique"], total_products),
                "%",
                "warning" if statuses["critique"] else "good",
                "Produits avec stock > 0 et stock <= seuil minimum.",
            ),
            self._kpi(
                "overstock_rate",
                "Taux surstock",
                pct(statuses["surstock"], total_products),
                "%",
                "warning" if statuses["surstock"] else "good",
                "Produits avec stock >= seuil maximum.",
            ),
            self._kpi(
                "coverage_days",
                "Couverture moyenne",
                safe_round(coverage, 1),
                "j",
                "warning" if coverage is not None and coverage < 7 else "neutral",
                "Stock actuel total / ventes moyennes journalières de la période.",
            ),
            self._kpi(
                "rotation",
                "Rotation moyenne",
                safe_round(rotation, 2),
                "x",
                "neutral",
                "Unités vendues période / stock moyen historique période si disponible.",
            ),
            self._kpi(
                "avg_historical_stock",
                "Stock moyen historique",
                safe_round(avg_stock_historical, 2),
                "",
                "good" if avg_stock_historical is not None else "warning",
                "Moyenne de historique_ventes.stock sur la période.",
            ),
            self._kpi(
                "units_sold",
                "Unités vendues",
                safe_round(total_units, 0),
                "",
                "neutral",
                f"Source utilisée : {sales_source}.",
            ),
            self._kpi(
                "revenue",
                "CA période",
                safe_round(revenue, 2),
                "TND",
                "neutral",
                "Somme unités vendues × prix de vente.",
            ),
        ]

        charts = {
            "stock_vs_sales": self._group_sales_by_day(sales),
            "stock_status_distribution": [
                {"name": "rupture", "value": statuses["rupture"], "colorKey": "danger"},
                {"name": "critique", "value": statuses["critique"], "colorKey": "warning"},
                {"name": "normal", "value": statuses["normal"], "colorKey": "success"},
                {"name": "surstock", "value": statuses["surstock"], "colorKey": "info"},
            ],
            "category_risk": [
                dict({"categorie": key}, **value)
                for key, value in sorted(category_status.items())
            ],
            "sales_by_category": self._group_sales_by_category(sales),
            "restock_by_category": [
                {
                    "categorie": key,
                    "quantite_a_commander": safe_round(value["quantite_a_commander"], 0),
                    "produits_critiques": value["produits_critiques"],
                    "ruptures": value["ruptures"],
                }
                for key, value in sorted(
                    category_restock.items(),
                    key=lambda item: item[1]["quantite_a_commander"],
                    reverse=True,
                )
                if value["quantite_a_commander"] > 0 or value["produits_critiques"] > 0
            ],
            "coverage_by_category": [
                {
                    "categorie": key,
                    "coverage_days": safe_round(
                        value["coverage_sum"] / value["coverage_count"], 1
                    ) if value["coverage_count"] else None,
                    "products": value["products"],
                    "risk_products": value["risk_products"],
                }
                for key, value in sorted(
                    category_coverage.items(),
                    key=lambda item: (
                        item[1]["coverage_sum"] / item[1]["coverage_count"]
                        if item[1]["coverage_count"] else 999999
                    )
                )
            ],
        }

        insights = [
            {
                "type": "stock",
                "status": "danger" if statuses["rupture"] else "good",
                "title": "Ruptures à traiter",
                "message": (
                    f"{statuses['rupture']} produit(s) sont en rupture. "
                    "Les produits prioritaires contiennent une justification métier."
                ),
            },
            {
                "type": "data",
                "status": "warning" if sales_source == "none" else "good",
                "title": "Fiabilité ventes",
                "message": (
                    f"Source de vente utilisée : {sales_source}. "
                    "Période basée sur les dates réelles de la base, pas sur la date du PC/Docker."
                ),
            },
        ]

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

        for product in products:
            item = market.get(product.get("id"))
            position = self._market_position(product, item)

            if not position or not item or not item.get("avg_price"):
                continue

            positions[position] += 1
            category_positions[product.get("categorie") or "Sans catégorie"][position] += 1

            gap = (
                (as_float(product.get("prixVente")) - as_float(item["avg_price"]))
                / as_float(item["avg_price"])
            ) * 100

            gaps.append(gap)

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
                        "categorie": product.get("categorie"),
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

        by_id = {p["id"]: p for p in products if p.get("id") is not None}

        estimated_profit = 0.0

        for row in sales:
            product = by_id.get(row.get("product_id"))

            if (
                product
                and product.get("prixVente") is not None
                and product.get("prixCout") is not None
            ):
                estimated_profit += (
                    as_float(product.get("prixVente"))
                    - as_float(product.get("prixCout"))
                ) * as_float(row.get("units"))

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

        kpis = [
            self._kpi(
                "avg_margin",
                "Marge moyenne",
                safe_round(avg_margin, 2),
                "%",
                "good" if avg_margin is not None and avg_margin >= 20 else "warning",
                "Moyenne des marges produits : (prix vente - prix coût) / prix vente.",
            ),
            self._kpi(
                "promo_rate",
                "Produits en promotion",
                pct(len(promos), total_products),
                "%",
                "neutral",
                "Produits liés à une promotion active.",
            ),
            self._kpi(
                "market_gap",
                "Écart moyen marché",
                safe_round(mean(gaps), 2) if gaps else None,
                "%",
                "neutral",
                "Écart moyen vs prix concurrent moyen.",
            ),
            self._kpi(
                "under_market",
                "Sous marché",
                positions["sous_marche"],
                "",
                "warning" if positions["sous_marche"] else "good",
                "Prix interne < 97% du prix concurrent moyen.",
            ),
            self._kpi(
                "over_market",
                "Au-dessus marché",
                positions["au_dessus"],
                "",
                "warning" if positions["au_dessus"] else "good",
                "Prix interne > 103% du prix concurrent moyen.",
            ),
            self._kpi(
                "estimated_profit",
                "Profit estimé",
                safe_round(estimated_profit, 2),
                "TND",
                "neutral",
                f"Calculé sur les ventes source {sales_source}.",
            ),
        ]

        charts = {
            "market_position_by_category": [
                dict({"categorie": key}, **value)
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
        f, products, sales_source, sales, promos, market, data_warnings = self._base(params)

        total_products = len(products)

        statuses = defaultdict(int)
        for product in products:
            statuses[self._stock_status(product)] += 1

        revenue = sum(as_float(row.get("revenue")) for row in sales)

        by_id = {p["id"]: p for p in products if p.get("id") is not None}

        estimated_profit = 0.0

        for row in sales:
            product = by_id.get(row.get("product_id"))

            if (
                product
                and product.get("prixVente") is not None
                and product.get("prixCout") is not None
            ):
                estimated_profit += (
                    as_float(product.get("prixVente"))
                    - as_float(product.get("prixCout"))
                ) * as_float(row.get("units"))

        market_covered = len(
            [
                p["id"]
                for p in products
                if p.get("id") in market and market[p["id"]].get("count", 0) > 0
            ]
        )

        promo_count = len([p for p in products if p.get("id") in promos])

        kpis = [
            self._kpi(
                "revenue",
                "CA période",
                safe_round(revenue, 2),
                "TND",
                "neutral",
                f"CA calculé depuis {sales_source}.",
            ),
            self._kpi(
                "estimated_profit",
                "Profit estimé",
                safe_round(estimated_profit, 2),
                "TND",
                "neutral",
                "Profit estimé = somme((prix vente - prix coût) × unités vendues).",
            ),
            self._kpi(
                "total_products",
                "Produits suivis",
                total_products,
                "",
                "neutral",
                "Nombre de produits après filtres.",
            ),
            self._kpi(
                "stock_risk",
                "Produits à risque stock",
                statuses["rupture"] + statuses["critique"],
                "",
                "danger" if statuses["rupture"] else "warning" if statuses["critique"] else "good",
                "Rupture + critique.",
            ),
            self._kpi(
                "market_coverage",
                "Couverture concurrentielle",
                pct(market_covered, total_products),
                "%",
                "good" if market_covered else "warning",
                "Produits avec prix concurrent fiable.",
            ),
            self._kpi(
                "promo_rate",
                "Taux promotion",
                pct(promo_count, total_products),
                "%",
                "neutral",
                "Produits en promotion active.",
            ),
        ]

        category_finance = defaultdict(
            lambda: {
                "units": 0.0,
                "revenue": 0.0,
                "profit": 0.0,
            }
        )

        for row in sales:
            category = row.get("categorie") or "Sans catégorie"
            product = by_id.get(row.get("product_id"))

            units = as_float(row.get("units"))
            revenue_row = as_float(row.get("revenue"))
            profit_row = 0.0

            if (
                product
                and product.get("prixVente") is not None
                and product.get("prixCout") is not None
            ):
                profit_row = (
                    as_float(product.get("prixVente"))
                    - as_float(product.get("prixCout"))
                ) * units

            category_finance[category]["units"] += units
            category_finance[category]["revenue"] += revenue_row
            category_finance[category]["profit"] += profit_row

        charts = {
            "finance_by_category": [
                {
                    "categorie": key,
                    "units": safe_round(value["units"], 2),
                    "revenue": safe_round(value["revenue"], 2),
                    "profit": safe_round(value["profit"], 2),
                }
                for key, value in sorted(
                    category_finance.items(),
                    key=lambda item: item[1]["revenue"],
                    reverse=True,
                )
            ],
            "stock_status_distribution": [
                {"name": "rupture", "value": statuses["rupture"], "colorKey": "danger"},
                {"name": "critique", "value": statuses["critique"], "colorKey": "warning"},
                {"name": "normal", "value": statuses["normal"], "colorKey": "success"},
                {"name": "surstock", "value": statuses["surstock"], "colorKey": "info"},
            ],
            "sales_trend": self._group_sales_by_day(sales),
        }

        stock_risks: list[dict[str, Any]] = []
        sales_by_product = defaultdict(float)

        for row in sales:
            if row.get("product_id"):
                sales_by_product[row["product_id"]] += as_float(row.get("units"))

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
                    "statut": status,
                    "stock": as_float(product.get("stockDisponible")),
                    "ventes_periode": safe_round(sold, 2),
                    "why": (
                        f"Priorité manager : stock = {product.get('stockDisponible') or 0}, "
                        f"ventes période = {safe_round(sold, 2)}, seuil min = {seuil_min}."
                    ),
                    "detail_url": f"/app/stock/products/{product.get('id')}",
                }
            )

        stock_risks.sort(key=lambda item: 0 if item["statut"] == "rupture" else 1)

        tables = {
            "top_categories": charts["finance_by_category"][:10],
            "stock_risks": stock_risks[:12],
        }

        warnings = list(data_warnings)
        insights = []

        return self._contract(f, kpis, charts, tables, insights, warnings)