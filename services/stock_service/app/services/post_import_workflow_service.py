from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.tables import Competitor, Product
from app.services.competitor_service import _replace_catalogs
from app.services.scraping_client import ScrapingServiceClient

logger = logging.getLogger(__name__)


def _product_payload(product: Product) -> dict:
    return {
        "id": product.id,
        "sku": product.sku,
        "nom": product.nom,
        "name": product.nom,
        "marque": product.marque,
        "brand": product.marque,
        "description": product.description,
        "categorie": product.categorie,
        "category": product.categorie,
    }


def _active_competitors_count(db: Session) -> int:
    return db.query(Competitor).filter(Competitor.actif.is_(True)).count()


def _get_products_to_process(
    db: Session,
    product_ids: list[int] | None = None,
    max_products: int = 30,
) -> list[Product]:
    if product_ids:
        products = (
            db.query(Product)
            .filter(Product.id.in_(product_ids))
            .all()
        )

        order = {pid: index for index, pid in enumerate(product_ids)}
        products.sort(key=lambda product: order.get(product.id, 999999))

        return products

    return (
        db.query(Product)
        .order_by(Product.id.desc())
        .limit(max_products)
        .all()
    )


def _mark_products_without_competitors(
    db: Session,
    product_ids: list[int] | None = None,
    max_products: int = 30,
) -> list[dict]:
    products = _get_products_to_process(
        db=db,
        product_ids=product_ids,
        max_products=max_products,
    )

    details = []

    for product in products:
        product.analyse_concurrentielle_statut = "NO_COMPETITORS"
        product.analyse_concurrentielle_date = datetime.utcnow()

        if getattr(product, "statut_prix", None) != "PRIX_VALIDE":
            product.statut_prix = "RECOMMANDATION_PRETE"

        details.append(
            {
                "type": "product_scan",
                "product_id": product.id,
                "sku": product.sku,
                "status": "NO_COMPETITORS",
                "message": (
                    "Aucun concurrent actif. "
                    "La recommandation interne coût/marge reste disponible."
                ),
            }
        )

    db.commit()

    return details

def _discover_pending_competitors(db: Session, client: ScrapingServiceClient) -> dict:
    result = {
        "competitors_discovered": 0,
        "competitors_failed": 0,
        "details": [],
    }

    competitors = (
        db.query(Competitor)
        .filter(Competitor.actif.is_(True))
        .filter(Competitor.discovery_status.in_(["pending", "partial"]))
        .order_by(Competitor.id.desc())
        .limit(20)
        .all()
    )

    for competitor in competitors:
        try:
            discovery = client.discover_site(
                competitor_name=competitor.nom,
                site_url=competitor.site_url,
            )

            catalogs = discovery.get("catalogs", []) if isinstance(discovery, dict) else []
            keywords = discovery.get("keywords", []) if isinstance(discovery, dict) else []

            _replace_catalogs(competitor, catalogs, db)

            competitor.auto_keywords_json = keywords
            competitor.discovery_status = "ready" if catalogs else "partial"
            competitor.last_discovery_at = datetime.utcnow()
            competitor.last_discovery_error = None if catalogs else "Aucun catalogue détecté automatiquement."

            db.commit()

            result["competitors_discovered"] += 1
            result["details"].append(
                {
                    "type": "competitor_discovery",
                    "competitor_id": competitor.id,
                    "competitor": competitor.nom,
                    "catalogs": len(catalogs),
                    "status": competitor.discovery_status,
                }
            )

        except Exception as exc:
            logger.exception("Erreur discovery concurrent %s", competitor.id)

            competitor.discovery_status = "partial"
            competitor.last_discovery_at = datetime.utcnow()
            competitor.last_discovery_error = str(exc)

            db.commit()

            result["competitors_failed"] += 1
            result["details"].append(
                {
                    "type": "competitor_discovery",
                    "competitor_id": competitor.id,
                    "competitor": competitor.nom,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return result


def _scan_recent_products(
    db: Session,
    client: ScrapingServiceClient,
    max_products: int = 30,
    product_ids: list[int] | None = None,
) -> dict:
    result = {
        "products_to_scan": len(product_ids or []),
        "products_scanned": 0,
        "products_failed": 0,
        "details": [],
    }

    if _active_competitors_count(db) == 0:
        details = _mark_products_without_competitors(
            db=db,
            product_ids=product_ids,
            max_products=max_products,
        )

        result["details"].extend(details)
        result["products_to_scan"] = len(details)

        return result

    products = _get_products_to_process(
        db=db,
        product_ids=product_ids,
        max_products=max_products,
    )

    result["products_to_scan"] = len(products)

    for product in products:
        try:
            product.analyse_concurrentielle_statut = "RUNNING"
            product.analyse_concurrentielle_date = None

            if getattr(product, "statut_prix", None) != "PRIX_VALIDE":
                product.statut_prix = "EN_ATTENTE_PRICING"

            db.commit()

            scan = client.search_product_on_competitors(
                product=_product_payload(product),
                debug=False,
            )

            if scan.get("status") == "error":
                raise Exception(scan.get("error", "Erreur scraping inconnue"))

            product.analyse_concurrentielle_statut = "DONE"
            product.analyse_concurrentielle_date = datetime.utcnow()

            if getattr(product, "statut_prix", None) != "PRIX_VALIDE":
                product.statut_prix = "RECOMMANDATION_PRETE"

            db.commit()

            result["products_scanned"] += 1
            result["details"].append(
                {
                    "type": "product_scan",
                    "product_id": product.id,
                    "sku": product.sku,
                    "status": "DONE",
                    "scan_status": scan.get("status"),
                    "message": "Scan concurrents terminé.",
                }
            )

        except Exception as exc:
            logger.exception("Erreur scan produit %s", product.id)

            product.analyse_concurrentielle_statut = "FAILED"
            product.analyse_concurrentielle_date = datetime.utcnow()

            if getattr(product, "statut_prix", None) != "PRIX_VALIDE":
                product.statut_prix = "RECOMMANDATION_PRETE"

            db.commit()

            result["products_failed"] += 1
            result["details"].append(
                {
                    "type": "product_scan",
                    "product_id": product.id,
                    "sku": product.sku,
                    "status": "FAILED",
                    "error": str(exc),
                    "message": "Scraping échoué, mais recommandation interne disponible.",
                }
            )

    return result

def run_post_import_workflow_service(
    db: Session,
    table_name: str | None = None,
    max_products: int = 30,
    product_ids: list[int] | None = None,
) -> dict:
    table_name = (table_name or "").lower().strip()
    product_ids = product_ids or []

    client = ScrapingServiceClient()

    result = {
        "status": "success",
        "table": table_name or None,
        "active_competitors": _active_competitors_count(db),
        "product_ids": product_ids,
        "total_products_to_scan": len(product_ids),
        "competitors_discovered": 0,
        "competitors_failed": 0,
        "products_scanned": 0,
        "products_failed": 0,
        "details": [],
    }

    if table_name in ("produits", "products", ""):
        scan_result = _scan_recent_products(
            db=db,
            client=client,
            max_products=max_products,
            product_ids=product_ids,
        )

        result["total_products_to_scan"] = scan_result["products_to_scan"]
        result["products_scanned"] += scan_result["products_scanned"]
        result["products_failed"] += scan_result["products_failed"]
        result["details"].extend(scan_result["details"])

        return result

    if table_name in ("competitor_added", "concurrent_added"):
        discovery_result = _discover_pending_competitors(
            db=db,
            client=client,
        )

        result["competitors_discovered"] += discovery_result["competitors_discovered"]
        result["competitors_failed"] += discovery_result["competitors_failed"]
        result["details"].extend(discovery_result["details"])

        scan_result = _scan_recent_products(
            db=db,
            client=client,
            max_products=max_products,
            product_ids=product_ids,
        )

        result["total_products_to_scan"] = scan_result["products_to_scan"]
        result["products_scanned"] += scan_result["products_scanned"]
        result["products_failed"] += scan_result["products_failed"]
        result["details"].extend(scan_result["details"])

        return result

    if table_name in (
        "concurrents",
        "competitors",
        "produits_concurrents",
        "competitor_products",
    ):
        result["status"] = "skipped"
        result["message"] = (
            "L'import fichier des concurrents et produits concurrents est désactivé."
        )

        return result

    result["status"] = "skipped"
    result["message"] = f"Aucun workflow prévu pour la table '{table_name}'."

    return result