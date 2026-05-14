from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.services.scraping_service import ScrapingService
from app.services.stock_client import StockServiceClient
from app.services.alert_client import AlertClient


STATE_FILE = Path("/app/.scheduler/dual_scraping_scheduler.json")
CHECK_EVERY_SECONDS = 5

_scheduler_started = False

APP_TIMEZONE = "Africa/Tunis"


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(APP_TIMEZONE)
    except Exception:
        return ZoneInfo("Africa/Tunis")


def _now() -> datetime:
    """
    Heure métier du projet.
    """
    return datetime.now(_tz()).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _parse_datetime(value: str) -> datetime:
    """
    Accepte :
    - 2026-05-05T11:35
    - 2026-05-05T11:35:00
    - 2026-05-05 11:35:00
    - 2026-05-05T09:00:00Z

    Règle importante :
    - une date SANS timezone = heure locale métier Africa/Tunis ;
    - une date AVEC timezone/Z = convertie vers Africa/Tunis.

    Cela évite le bug : l'utilisateur choisit 10h, le front envoie 09h UTC,
    puis le backend l'enregistre comme 09h locale.
    """
    if not value:
        raise ValueError("run_at est obligatoire.")

    clean = str(value).strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(clean)
    except Exception:
        raise ValueError(
            "Format run_at invalide. Exemple attendu : 2026-05-05T11:35:00"
        )

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_tz()).replace(tzinfo=None)

    return parsed


def _ensure_future_datetime(dt: datetime) -> None:
    if dt <= _now():
        raise ValueError("La date de planification doit être dans le futur.")




def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    return []


def _first_value(data: dict, keys: list[str], default=None):
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def _normalize_scraped_row(row: dict, source_type: str = "catalog", parent_product: dict | None = None) -> dict:
    """
    Structure unique pour tous les résultats affichés dans le front :
    - scraping par produit
    - scraping catalogue manuel/config
    - scraping catalogue planifié
    """
    if not isinstance(row, dict):
        return {}

    produit_interne = (
        row.get("produitInterne")
        or row.get("produit_interne")
        or row.get("internal_product")
        or row.get("product")
        or parent_product
    )

    produit_scrape = row.get("produitScrape") or row.get("produit_scrape") or {
        "id": row.get("id"),
        "nomProduit": _first_value(row, ["nomProduit", "nom_produit", "name", "title"]),
        "skuConcurrent": _first_value(row, ["skuConcurrent", "sku_concurrent"]),
        "urlProduit": _first_value(row, ["urlProduit", "url_produit", "url"]),
        "prixConcurrent": _first_value(row, ["prixConcurrent", "prix_concurrent", "price"]),
        "ancienPrixConcurrent": _first_value(row, ["ancienPrixConcurrent", "ancien_prix_concurrent", "old_price"]),
        "isPromo": _first_value(row, ["isPromo", "is_promo"], False),
        "disponibilite": _first_value(row, ["disponibilite", "availability"]),
        "concurrent": _first_value(row, ["concurrent", "competitor_name", "concurrentName"]),
        "concurrentId": _first_value(row, ["concurrentId", "concurrent_id", "competitor_id"]),
    }

    score = _first_value(row, ["score", "scoreMatching", "score_matching", "match_score"])
    statut = _first_value(row, ["statut", "statutMatching", "statut_matching", "match_status"], "UNKNOWN")

    try:
        score_float = float(score) if score is not None else None
    except Exception:
        score_float = None

    action_required = (
        str(statut).upper() in {"MANUAL_REVIEW", "REVIEW", "A_VALIDER"}
        or (score_float is not None and score_float != 100)
    )

    return {
        "id": row.get("id"),
        "sourceType": source_type,
        "produitInterne": produit_interne,
        "produit_interne": produit_interne,
        "produitScrape": produit_scrape,
        "produit_scrape": produit_scrape,
        "concurrent": produit_scrape.get("concurrent") or row.get("concurrent") or row.get("competitor_name"),
        "concurrentId": produit_scrape.get("concurrentId") or row.get("concurrentId") or row.get("concurrent_id") or row.get("competitor_id"),
        "score": score_float if score_float is not None else score,
        "scoreMatching": score_float if score_float is not None else score,
        "match_score": score_float if score_float is not None else score,
        "statut": statut,
        "statutMatching": statut,
        "match_status": statut,
        "actionRequired": action_required,
        "canValidate": action_required,
        "raw": row,
    }


def _normalize_scraped_rows(rows: list, source_type: str = "catalog", parent_product: dict | None = None) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()

    for row in rows or []:
        item = _normalize_scraped_row(row, source_type=source_type, parent_product=parent_product)
        if not item:
            continue
        key = str(item.get("id") or item.get("produitScrape", {}).get("urlProduit") or len(normalized))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)

    return normalized


def _extract_catalog_items(result: dict) -> list[dict]:
    if not isinstance(result, dict):
        return []

    rows: list[dict] = []
    rows.extend(_as_list(result.get("items")))
    rows.extend(_as_list(result.get("scraped_items")))
    rows.extend(_as_list(result.get("scraped_products")))
    rows.extend(_as_list(result.get("saved_items")))

    for child in _as_list(result.get("results")):
        rows.extend(_as_list(child.get("items")))
        rows.extend(_as_list(child.get("scraped_items")))
        rows.extend(_as_list(child.get("scraped_products")))
        rows.extend(_as_list(child.get("saved_items")))

    return _normalize_scraped_rows(rows, source_type="catalog")


def _normalize_ids(values: list[int] | None) -> list[int]:
    if not values:
        return []

    ids: list[int] = []

    for value in values:
        try:
            product_id = int(value)
            if product_id > 0:
                ids.append(product_id)
        except Exception:
            continue

    return list(dict.fromkeys(ids))


class DualScrapingScheduler:
    """
    Scheduler interne du scraping_service.

    Il gère deux types de jobs :

    1. Jobs produits sélectionnés :
       - l'utilisateur choisit des product_ids
       - le worker lance la recherche ciblée à l'heure prévue
       - chaque produit est recherché chez les concurrents

    2. Jobs catalogues :
       - scraping manuel ou périodique des catalogues concurrents
       - lancé dans un thread séparé
       - évite les 504 côté frontend/API gateway

    L'état est sauvegardé dans un fichier JSON.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.running_product_job_ids: set[str] = set()
        self.catalog_running = False

        self.state: dict[str, Any] = {
            "product_jobs": {},
            "catalog_frequency": {
                "enabled": False,
                "interval_minutes": 360,
                "competitor_id": None,
                "next_run_at": None,
                "last_run_at": None,
                "last_finished_at": None,
                "last_status": "IDLE",
                "last_error": None,
                "current_run": None,
                "runs_history": [],
            },
        }

        self._load()

    # ------------------------------------------------------------------
    # Persistence JSON
    # ------------------------------------------------------------------
    def _load(self):
        try:
            if not STATE_FILE.exists():
                return

            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

            if isinstance(data, dict):
                self.state["product_jobs"] = data.get("product_jobs", {}) or {}
                self.state["catalog_frequency"].update(
                    data.get("catalog_frequency", {}) or {}
                )

                current_run = self.state["catalog_frequency"].get("current_run")
                if current_run and current_run.get("status") == "RUNNING":
                    current_run["status"] = "FAILED"
                    current_run["finished_at"] = _iso(_now())
                    current_run["error"] = (
                        "Le service a redémarré pendant l'exécution du scraping."
                    )

                    self.state["catalog_frequency"]["last_status"] = "FAILED"
                    self.state["catalog_frequency"]["last_error"] = current_run[
                        "error"
                    ]
                    self.state["catalog_frequency"]["last_finished_at"] = _iso(
                        _now()
                    )

        except Exception as exc:
            print(f"[dual-scheduler] Impossible de charger l'état: {exc}")

    def _save(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[dual-scheduler] Impossible de sauvegarder l'état: {exc}")

    # ------------------------------------------------------------------
    # Product scheduled jobs
    # ------------------------------------------------------------------
    def create_product_job(
        self,
        product_ids: list[int],
        run_at: str,
        fast: bool = True,
        debug: bool = False,
        title: str | None = None,
        allow_past: bool = False,
    ) -> dict:
        ids = _normalize_ids(product_ids)

        if not ids:
            raise ValueError("Sélectionne au moins un produit à scraper.")

        dt = _parse_datetime(run_at)
        if not allow_past:
            _ensure_future_datetime(dt)

        job_id = str(uuid.uuid4())[:8]

        job = {
            "id": job_id,
            "type": "selected_products",
            "title": title or f"Scraping de {len(ids)} produit(s)",
            "status": "SCHEDULED",
            "run_at": _iso(dt),
            "created_at": _iso(_now()),
            "started_at": None,
            "finished_at": None,
            "product_ids": ids,
            "fast": bool(fast),
            "debug": bool(debug),
            "total": len(ids),
            "processed": 0,
            "done": 0,
            "failed": 0,
            "items": [],
            "error": None,
        }

        with self.lock:
            self.state["product_jobs"][job_id] = job
            self._save()

        return job

    def list_product_jobs(self) -> list[dict]:
        with self.lock:
            jobs = list(self.state["product_jobs"].values())

        jobs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return jobs

    def get_product_job(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.state["product_jobs"].get(job_id)
            return dict(job) if job else None

    def cancel_product_job(self, job_id: str) -> dict:
        with self.lock:
            job = self.state["product_jobs"].get(job_id)

            if not job:
                raise ValueError("Job introuvable.")

            if job.get("status") == "RUNNING":
                raise ValueError("Impossible d'annuler un job déjà en cours.")

            job["status"] = "CANCELLED"
            job["finished_at"] = _iso(_now())
            self._save()

            return dict(job)

    def run_product_job_now(
        self,
        product_ids: list[int],
        fast: bool = True,
        debug: bool = False,
    ) -> dict:
        job = self.create_product_job(
            product_ids=product_ids,
            run_at=_iso(_now()),
            fast=fast,
            debug=debug,
            title="Scraping immédiat produits sélectionnés",
            allow_past=True,
        )

        self._launch_product_job_thread(job["id"])
        return job

    def _launch_product_job_thread(self, job_id: str):
        with self.lock:
            if job_id in self.running_product_job_ids:
                return

            job = self.state["product_jobs"].get(job_id)

            if not job or job.get("status") not in ("SCHEDULED", "FAILED"):
                return

            self.running_product_job_ids.add(job_id)

        thread = threading.Thread(
            target=self._run_product_job,
            args=(job_id,),
            daemon=True,
        )
        thread.start()

    def _run_product_job(self, job_id: str):
        stock_client = StockServiceClient()
        scraper = ScrapingService()
        alerts = AlertClient()

        try:
            with self.lock:
                job = self.state["product_jobs"].get(job_id)

                if not job:
                    return

                job["status"] = "RUNNING"
                job["started_at"] = _iso(_now())
                job["processed"] = 0
                job["done"] = 0
                job["failed"] = 0
                job["items"] = []
                job["error"] = None
                self._save()

            product_ids = job.get("product_ids", [])
            products = stock_client.get_products_by_ids(product_ids)

            product_by_id = {
                int(product.get("id")): product
                for product in products
                if product.get("id") is not None
            }

            for product_id in product_ids:
                product = product_by_id.get(int(product_id))

                if not product:
                    item = {
                        "product_id": product_id,
                        "sku": None,
                        "nom": None,
                        "status": "FAILED",
                        "error": "Produit introuvable dans stock_service.",
                    }

                    with self.lock:
                        job = self.state["product_jobs"][job_id]
                        job["processed"] += 1
                        job["failed"] += 1
                        job["items"].append(item)
                        self._save()

                    continue

                try:
                    result = scraper.search_product_on_all_competitors(
                        product=product,
                        debug=bool(job.get("debug", False)),
                        fast=bool(job.get("fast", True)),
                    )

                    if result.get("status") == "error":
                        raise Exception(
                            result.get("error", "Erreur scraping inconnue")
                        )

                    summary = result.get("summary", {}) or {}
                    scraped_products = result.get("scraped_products", []) or result.get("saved_items", []) or []
                    validation_items = _normalize_scraped_rows(
                        scraped_products,
                        source_type="product",
                        parent_product=product,
                    )

                    item = {
                        "product_id": product_id,
                        "sku": product.get("sku"),
                        "nom": product.get("nom") or product.get("name"),
                        "status": "DONE",
                        "products_found": summary.get("productsFound", 0),
                        "products_saved": summary.get("productsSaved", 0),
                        "manual_review": summary.get("manualReview", 0),
                        "matched": summary.get("matched", 0),
                        "ignored": summary.get("ignored", 0),
                        "scraped_products": scraped_products,
                        "saved_items": scraped_products,
                        "validation_items": validation_items,
                        "items": validation_items,
                    }

                    with self.lock:
                        job = self.state["product_jobs"][job_id]
                        job["processed"] += 1
                        job["done"] += 1
                        job["items"].append(item)
                        self._save()

                except Exception as exc:
                    item = {
                        "product_id": product_id,
                        "sku": product.get("sku"),
                        "nom": product.get("nom") or product.get("name"),
                        "status": "FAILED",
                        "error": str(exc),
                    }

                    with self.lock:
                        job = self.state["product_jobs"][job_id]
                        job["processed"] += 1
                        job["failed"] += 1
                        job["items"].append(item)
                        self._save()

            final_job = None
            with self.lock:
                job = self.state["product_jobs"][job_id]
                job["status"] = "DONE" if job["failed"] == 0 else "DONE_WITH_ERRORS"
                job["finished_at"] = _iso(_now())
                all_scraped_items = []
                for product_item in job.get("items", []) or []:
                    all_scraped_items.extend(product_item.get("validation_items", []) or product_item.get("items", []) or [])
                job["scraped_items"] = all_scraped_items
                job["validation_items"] = [item for item in all_scraped_items if item.get("actionRequired") or item.get("canValidate")]
                final_job = dict(job)
                self._save()

            alerts.product_job_success(job=final_job or {})

        except Exception as exc:
            with self.lock:
                job = self.state["product_jobs"].get(job_id)

                if job:
                    job["status"] = "FAILED"
                    job["finished_at"] = _iso(_now())
                    job["error"] = str(exc)
                    self._save()

            alerts.product_job_error(job_id=job_id, error=str(exc))

        finally:
            with self.lock:
                self.running_product_job_ids.discard(job_id)

    # ------------------------------------------------------------------
    # Catalog frequency / catalog scraping jobs
    # ------------------------------------------------------------------
    def configure_catalog_frequency(
        self,
        enabled: bool,
        interval_minutes: int,
        competitor_id: int | None = None,
    ) -> dict:
        interval = max(5, int(interval_minutes))

        with self.lock:
            config = self.state["catalog_frequency"]

            config["enabled"] = bool(enabled)
            config["interval_minutes"] = interval
            config["competitor_id"] = competitor_id
            config["next_run_at"] = _iso(_now() + timedelta(minutes=interval))
            self._save()

            return dict(config)

    def get_catalog_frequency(self) -> dict:
        with self.lock:
            return dict(self.state["catalog_frequency"])

    def run_catalog_now(self, competitor_id: int | None = None) -> dict:
        """
        Lance le scraping catalogue en arrière-plan.

        Important :
        Cette fonction ne doit jamais appeler directement scrape_due_or_all().
        Elle crée seulement un thread puis retourne l'état courant.
        """
        self._launch_catalog_thread(
            trigger="manual",
            competitor_id_override=competitor_id,
        )

        return self.get_catalog_frequency()

    def _launch_catalog_thread(
        self,
        trigger: str = "scheduled",
        competitor_id_override: int | None = None,
    ):
        with self.lock:
            if self.catalog_running:
                return

            self.catalog_running = True

            config = self.state["catalog_frequency"]

            selected_competitor_id = (
                competitor_id_override
                if competitor_id_override is not None
                else config.get("competitor_id")
            )

            config["last_status"] = "RUNNING"
            config["last_error"] = None
            config["last_run_at"] = _iso(_now())
            config["current_run"] = {
                "trigger": trigger,
                "status": "RUNNING",
                "started_at": _iso(_now()),
                "finished_at": None,
                "competitor_id": selected_competitor_id,
            }

            self._save()

        thread = threading.Thread(
            target=self._run_catalog_scraping,
            args=(trigger, competitor_id_override),
            daemon=True,
        )

        thread.start()

    def _run_catalog_scraping(
        self,
        trigger: str = "scheduled",
        competitor_id_override: int | None = None,
    ):
        scraper = ScrapingService()
        alerts = AlertClient()

        try:
            with self.lock:
                config = self.state["catalog_frequency"]

                competitor_id = (
                    competitor_id_override
                    if competitor_id_override is not None
                    else config.get("competitor_id")
                )

            result = scraper.scrape_due_or_all(competitor_id=competitor_id)
            normalized_items = _extract_catalog_items(result)
            if isinstance(result, dict):
                result["items"] = normalized_items
                result["scraped_items"] = normalized_items
                result["validation_items"] = [item for item in normalized_items if item.get("actionRequired") or item.get("canValidate")]

            with self.lock:
                config = self.state["catalog_frequency"]

                config["last_status"] = "DONE"
                config["last_error"] = None
                config["last_finished_at"] = _iso(_now())
                config["current_run"] = {
                    **(config.get("current_run") or {}),
                    "status": "DONE",
                    "finished_at": _iso(_now()),
                    "result": result,
                    "items": normalized_items,
                    "scraped_items": normalized_items,
                    "validation_items": [item for item in normalized_items if item.get("actionRequired") or item.get("canValidate")],
                }

                config["runs_history"] = [
                    config["current_run"],
                    *(config.get("runs_history") or []),
                ][:20]

                if config.get("enabled"):
                    config["next_run_at"] = _iso(
                        _now()
                        + timedelta(
                            minutes=int(config.get("interval_minutes") or 360)
                        )
                    )

                self._save()

            alerts.catalog_success(trigger=trigger, result=result)

        except Exception as exc:
            with self.lock:
                config = self.state["catalog_frequency"]

                config["last_status"] = "FAILED"
                config["last_error"] = str(exc)
                config["last_finished_at"] = _iso(_now())
                config["current_run"] = {
                    **(config.get("current_run") or {}),
                    "status": "FAILED",
                    "finished_at": _iso(_now()),
                    "error": str(exc),
                }

                config["runs_history"] = [
                    config["current_run"],
                    *(config.get("runs_history") or []),
                ][:20]

                if config.get("enabled"):
                    config["next_run_at"] = _iso(
                        _now()
                        + timedelta(
                            minutes=int(config.get("interval_minutes") or 360)
                        )
                    )

                self._save()

            alerts.catalog_error(trigger=trigger, error=str(exc))

        finally:
            with self.lock:
                self.catalog_running = False

    # ------------------------------------------------------------------
    # Main worker
    # ------------------------------------------------------------------
    def tick(self):
        now = _now()

        # Jobs produits sélectionnés
        with self.lock:
            jobs = list(self.state["product_jobs"].values())

        for job in jobs:
            if job.get("status") != "SCHEDULED":
                continue

            try:
                run_at = _parse_datetime(job.get("run_at"))
            except Exception:
                continue

            if run_at <= now:
                self._launch_product_job_thread(job["id"])

        # Fréquence scraping catalogues/sites
        with self.lock:
            config = self.state["catalog_frequency"]
            enabled = bool(config.get("enabled"))
            next_run_at = config.get("next_run_at")

        if enabled and next_run_at:
            try:
                dt = _parse_datetime(next_run_at)

                if dt <= now:
                    self._launch_catalog_thread(trigger="scheduled")
            except Exception:
                pass

    def status(self) -> dict:
        return {
            "product_jobs": self.list_product_jobs(),
            "catalog_frequency": self.get_catalog_frequency(),
        }


dual_scheduler = DualScrapingScheduler()


def start_scheduler() -> None:
    global _scheduler_started

    if _scheduler_started:
        return

    _scheduler_started = True

    def _worker():
        while True:
            try:
                dual_scheduler.tick()
            except Exception as exc:
                print(f"[dual-scheduler] erreur worker: {exc}")

            time.sleep(CHECK_EVERY_SECONDS)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    print("[dual-scheduler] worker démarré")