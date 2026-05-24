import logging
import os

import requests


logger = logging.getLogger(__name__)


class ScrapingServiceClient:
    def __init__(self):
        self.base_url = os.getenv(
            "SCRAPING_SERVICE_URL",
            "http://scraping_service:8060",
        ).rstrip("/")

        self.session = requests.Session()
    def discover_site(
        self,
        competitor_name: str,
        site_url: str,
    ) -> dict:
        """
        Lance la découverte d'un site concurrent (catalogues, keywords, sélecteurs).
        Appelle POST /discovery/site sur le scraping_service.
        """
        try:
            response = self.session.post(
                f"{self.base_url}/discovery/site",
                json={
                    "competitor_name": competitor_name,
                    "site_url": site_url,
                },
                timeout=(10, 300),
            )

            if response.status_code == 504:
                return {
                    "status": "timeout",
                    "catalogs": [],
                    "keywords": [],
                    "error": "La découverte du site a dépassé le délai autorisé côté scraping_service.",
                }

            response.raise_for_status()
            return response.json()

        except requests.exceptions.ReadTimeout:
            logger.warning(f"Découverte du site {site_url} trop longue.")
            return {
                "status": "timeout",
                "catalogs": [],
                "keywords": [],
                "error": "La découverte du site a pris trop de temps côté stock_service.",
            }

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"scraping_service inaccessible lors de la découverte: {e}")
            return {
                "status": "error",
                "catalogs": [],
                "keywords": [],
                "error": (
                    "scraping_service est inaccessible. "
                    "Vérifie que le conteneur scraping_service est bien lancé."
                ),
            }

        except requests.exceptions.HTTPError as e:
            logger.warning(f"Erreur HTTP découverte site: {e}")
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {
                "status": "error",
                "catalogs": [],
                "keywords": [],
                "error": detail,
            }

        except Exception as e:
            logger.warning(f"Découverte du site {site_url} échouée: {e}")
            return {
                "status": "error",
                "catalogs": [],
                "keywords": [],
                "error": str(e),
            }
            

    def run_product_job_now(
        self,
        product_ids: list[int],
        fast: bool = True,
        debug: bool = False,
        launched_by_user_id: int | None = None,
    ) -> dict:
        """
        Lance un seul job scraping produit côté scraping_service.

        Important :
        - Cette méthode ne considère pas le scraping comme terminé.
        - Elle crée un job asynchrone dans scraping_service.
        - Le scraping_service notifiera ensuite stock_service à la fin du job.
        """
        clean_ids = []
        for value in product_ids or []:
            try:
                product_id = int(value)
                if product_id > 0 and product_id not in clean_ids:
                    clean_ids.append(product_id)
            except Exception:
                continue

        if not clean_ids:
            return {
                "status": "error",
                "error": "Aucun product_id valide pour lancer le scraping.",
            }

        payload = {
            "product_ids": clean_ids,
            "fast": fast,
            "debug": debug,
            "launched_by_user_id": launched_by_user_id,
        }

        try:
            response = self.session.post(
                f"{self.base_url}/jobs/product-run-now",
                json=payload,
                timeout=(10, 60),
            )

            if response.status_code == 504:
                return {
                    "status": "timeout",
                    "error": "Le lancement du job scraping a dépassé le délai autorisé.",
                }

            response.raise_for_status()
            data = response.json()

            return {
                **data,
                "status": data.get("status") or "scheduled",
                "product_ids": clean_ids,
            }

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"scraping_service inaccessible: {e}")
            return {
                "status": "error",
                "error": (
                    "scraping_service est inaccessible. "
                    "Vérifie que le conteneur scraping_service est bien lancé."
                ),
            }

        except requests.exceptions.HTTPError as e:
            logger.warning(f"Erreur HTTP scraping_service: {e}")
            try:
                detail = response.json()
            except Exception:
                detail = response.text

            return {
                "status": "error",
                "error": detail,
            }

        except Exception as e:
            logger.warning(f"Lancement job scraping produits échoué: {e}")
            return {
                "status": "error",
                "error": str(e),
            }


    def search_product_on_competitors(
        self,
        product: dict,
        debug: bool = False,
    ) -> dict:
        """
        Recherche ciblée rapide d'un produit chez les concurrents.
        Appelle scraping_service via HTTP.
        Ne jamais importer directement scraping_service ici.
        """
        try:
            response = self.session.post(
                f"{self.base_url}/jobs/search-product",
                params={
                    "debug": debug,
                    "fast": True,   # toujours fast pour la route synchrone
                },
                json={
                    "product_id": product.get("id"),
                    "id": product.get("id"),
                    "sku": product.get("sku"),
                    "nom": product.get("nom"),
                    "name": product.get("nom"),
                    "marque": product.get("marque"),
                    "brand": product.get("marque"),
                    "description": product.get("description"),
                    "categorie": product.get("categorie"),
                    "category": product.get("categorie"),
                },
                # FIX: timeout réduit — le scraping_service doit finir en <150s
                # Le budget par concurrent est 25s × N concurrents + marge
                timeout=(10, 150),
            )

            if response.status_code == 504:
                return {
                    "status": "timeout",
                    "error": "Le scraping ciblé a dépassé le délai autorisé côté scraping_service.",
                }

            response.raise_for_status()
            return response.json()

        except requests.exceptions.ReadTimeout:
            logger.warning("Recherche ciblée produit trop longue.")
            return {
                "status": "timeout",
                "error": "Le scraping ciblé a dépassé le délai autorisé.",
            }

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"scraping_service inaccessible: {e}")
            return {
                "status": "error",
                "error": (
                    "scraping_service est inaccessible. "
                    "Vérifie que le conteneur scraping_service est bien lancé."
                ),
            }

        except requests.exceptions.HTTPError as e:
            logger.warning(f"Erreur HTTP scraping_service: {e}")

            try:
                detail = response.json()
            except Exception:
                detail = response.text

            return {
                "status": "error",
                "error": detail,
            }

        except Exception as e:
            logger.warning(f"Recherche ciblée produit échouée: {e}")
            return {
                "status": "error",
                "error": str(e),
            }