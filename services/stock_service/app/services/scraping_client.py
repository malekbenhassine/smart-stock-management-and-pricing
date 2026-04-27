"""
Client HTTP vers le scraping_service.
"""
import logging
import requests

logger = logging.getLogger(__name__)

SCRAPING_SERVICE_URL = "http://scraping_service:8060"


class ScrapingServiceClient:
    def __init__(self, base_url: str = SCRAPING_SERVICE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def discover_site(self, competitor_name: str, site_url: str) -> dict:
        response = self.session.post(
            f"{self.base_url}/discovery/site",
            json={"competitor_name": competitor_name, "site_url": site_url},
            timeout=(10, 90),
        )
        response.raise_for_status()
        return response.json()

    def run_scraping_for_competitor(self, competitor_id: int) -> dict:
        """Déclenche un scraping immédiat pour un concurrent spécifique."""
        try:
            response = self.session.post(
                f"{self.base_url}/jobs/run-now",
                json={"competitor_id": competitor_id},
                timeout=(10, 300),
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Scraping concurrent {competitor_id} échoué: {e}")
            return {"status": "error", "competitor_id": competitor_id, "error": str(e)}

    def run_scraping_all(self) -> dict:
        """Déclenche un scraping sur tous les concurrents actifs."""
        try:
            response = self.session.post(
                f"{self.base_url}/jobs/run-now",
                json={},
                timeout=(10, 600),
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Scraping global échoué: {e}")
            return {"status": "error", "error": str(e)}

    def search_product_on_competitors(self, product: dict) -> dict:
        """
        Recherche ciblée d'un produit chez tous les concurrents actifs.
        Utilisée après l'ajout d'un nouveau produit.
        """
        try:
            response = self.session.post(
                f"{self.base_url}/jobs/search-product",
                json={
                    "product_id": product.get("id"),
                    "sku": product.get("sku"),
                    "nom": product.get("nom"),
                    "marque": product.get("marque"),
                    "description": product.get("description"),
                    "categorie": product.get("categorie"),
                },
                timeout=(10, 240),
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Recherche ciblée produit échouée: {e}")
            return {"status": "error", "error": str(e)}