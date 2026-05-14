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

    def get_competitors(self) -> List[CompetitorModel]:
        response = self.session.get(
            f"{self.base_url}/competitors",
            timeout=(10, 45),
        )
        response.raise_for_status()
        data = response.json()

        competitors = []
        for item in data:
            try:
                competitors.append(CompetitorModel(**item))
            except ValidationError:
                continue

        return competitors

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
            totals["saved_items"].extend(result.get("saved_items", []) or result.get("scraped_products", []) or [])
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
