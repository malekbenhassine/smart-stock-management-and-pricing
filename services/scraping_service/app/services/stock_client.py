from typing import List, Optional
import requests
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.scraping_schemas import CompetitorModel, ProductCompetitorPayload


class StockServiceClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.STOCK_SERVICE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _competitors_from_response(self, data) -> List[CompetitorModel]:
        if isinstance(data, dict):
            raw_items = (
                data.get("items")
                or data.get("data")
                or data.get("competitors")
                or data.get("concurrents")
                or []
            )
        else:
            raw_items = data

        competitors: List[CompetitorModel] = []
        for item in raw_items or []:
            try:
                competitors.append(CompetitorModel(**item))
            except ValidationError:
                continue

        return competitors

    def get_competitors(self) -> List[CompetitorModel]:
        response = self.session.get(
            f"{self.base_url}/competitors",
            timeout=(10, 45),
        )
        response.raise_for_status()
        return self._competitors_from_response(response.json())

    def get_due_competitors(self) -> List[CompetitorModel]:
        response = self.session.get(
            f"{self.base_url}/competitors/due",
            timeout=(10, 45),
        )
        response.raise_for_status()
        return self._competitors_from_response(response.json())

    def get_competitor_by_id(self, competitor_id: int) -> Optional[CompetitorModel]:
        response = self.session.get(
            f"{self.base_url}/competitors/{competitor_id}",
            timeout=(10, 45),
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return CompetitorModel(**response.json())

    def save_competitor_products(self, items, chunk_size: int = 40):
        """
        Envoie les produits scrapés au stock_service par petits lots.
        Objectif : éviter les timeouts quand /jobs/run-now scrape beaucoup de produits.
        """
        if not items:
            return {
                "status": "success",
                "total_received": 0,
                "inserted": 0,
                "updated": 0,
                "matched": 0,
                "manual_review": 0,
                "ignored": 0,
                "invalid": 0,
                "manual_items": [],
                "saved_items": [],
                "scraped_products": [],
                "invalid_items": [],
            }

        totals = {
            "status": "success",
            "total_received": 0,
            "inserted": 0,
            "updated": 0,
            "matched": 0,
            "manual_review": 0,
            "ignored": 0,
            "invalid": 0,
            "manual_items": [],
            "saved_items": [],
            "scraped_products": [],
            "invalid_items": [],
        }

        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]

            payload = {
                "items": [
                    item.model_dump() if hasattr(item, "model_dump") else item
                    for item in chunk
                ]
            }

            response = self.session.post(
                f"{self.base_url}/competitor-products/from-scraping",
                json=payload,
                timeout=(10, 300),
            )

            response.raise_for_status()
            result = response.json()

            totals["total_received"] += int(result.get("total_received", 0) or 0)
            totals["inserted"] += int(result.get("inserted", 0) or 0)
            totals["updated"] += int(result.get("updated", 0) or 0)
            totals["matched"] += int(result.get("matched", 0) or 0)
            totals["manual_review"] += int(result.get("manual_review", 0) or 0)
            totals["ignored"] += int(result.get("ignored", 0) or 0)
            totals["invalid"] += int(result.get("invalid", 0) or 0)
            totals["manual_items"].extend(result.get("manual_items", []) or [])
            totals["saved_items"].extend(result.get("saved_items", []) or result.get("scraped_products", []) or result.get("items", []) or [])
            totals["invalid_items"].extend(result.get("invalid_items", []) or [])
            totals["scraped_products"] = totals["saved_items"]

        return totals

    def update_last_scraping(self, competitor_id: int) -> dict:
        response = self.session.patch(
            f"{self.base_url}/competitors/{competitor_id}/last-scraping",
            timeout=(10, 30),
        )
        response.raise_for_status()
        return response.json()
    

    def get_product_by_id(self, product_id: int) -> Optional[dict]:
        response = self.session.get(
            f"{self.base_url}/products/{product_id}",
            timeout=(10, 30),
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        data = response.json()

        # Certains endpoints retournent {"product": {...}}, d'autres directement le produit.
        if isinstance(data, dict) and "product" in data:
            return data["product"]

        return data

    def get_products_by_ids(self, product_ids: List[int]) -> List[dict]:
        products = []

        for product_id in product_ids:
            product = self.get_product_by_id(product_id)

            if product:
                products.append(product)

        return products


    def mark_product_competitive_analysis_finished(
        self,
        product_id: int,
        status: str = "DONE",
        products_saved: int = 0,
        matched: int = 0,
        manual_review: int = 0,
        ignored: int = 0,
        error: str | None = None,
    ) -> dict:
        """
        Informe stock_service que le scraping réel d'un produit est terminé.
        Cela permet aux produits ajoutés/importés de sortir de RUNNING uniquement
        quand le job scraping_service est réellement fini.
        """
        payload = {
            "status": status,
            "products_saved": products_saved,
            "matched": matched,
            "manual_review": manual_review,
            "ignored": ignored,
            "error": error,
        }

        response = self.session.post(
            f"{self.base_url}/products/{product_id}/competitive-analysis-finished",
            json=payload,
            timeout=(10, 60),
        )
        response.raise_for_status()
        return response.json()


    def trigger_price_recommendation_ready_alert(self, product_id: int) -> dict:
        """
        Appelé après la fin du scraping produit.
        Déclenche côté stock_service l'alerte PRICE_RECOMMENDATION_AVAILABLE.
        """
        response = self.session.post(
            f"{self.base_url}/products/{product_id}/price-recommendation-ready-alert",
            timeout=(10, 60),
        )
        response.raise_for_status()
        return response.json()

    def mark_competitive_analysis_finished(
        self,
        product_id: int,
        status: str = "DONE",
        products_saved: int = 0,
        matched: int = 0,
        manual_review: int = 0,
        ignored: int = 0,
        error: str | None = None,
    ) -> dict:
        payload = {
            "status": status,
            "products_saved": products_saved,
            "matched": matched,
            "manual_review": manual_review,
            "ignored": ignored,
        }

        if error:
            payload["error"] = error

        response = self.session.post(
            f"{self.base_url}/products/{product_id}/competitive-analysis-finished",
            json=payload,
            timeout=(10, 60),
        )
        response.raise_for_status()
        return response.json()