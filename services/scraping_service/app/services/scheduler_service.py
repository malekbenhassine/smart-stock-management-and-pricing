from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import os
from zoneinfo import ZoneInfo
from app.services.scraping_service import ScrapingService
from app.services.stock_client import StockServiceClient


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
    Docker peut rester en UTC, mais le scheduler travaille avec l'heure locale.
    Par défaut : Africa/Tunis.
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

    Si le front envoie une date sans timezone, on la considère
    comme une heure locale du projet : Africa/Tunis par défaut.
    """
    if not value:
        raise ValueError("run_at est obligatoire.")

    clean = str(value).strip().replace("Z", "")

    try:
        parsed = datetime.fromisoformat(clean)
    except Exception:
        raise ValueError(
            "Format run_at invalide. Exemple attendu : 2026-05-05T11:35:00"
        )

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_tz()).replace(tzinfo=None)

    return parsed

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
    Méthode simple :

    1) Jobs produits sélectionnés :
       - l'utilisateur choisit product_ids + run_at
       - le worker lance à l'heure prévue
       - recherche ciblée produit par produit chez tous les concurrents

    2) Fréquence catalogues/sites :
       - ex: toutes les 6h
       - lance scrape_due_or_all() ou scrape_due_or_all(competitor_id)
       - utile pour rafraîchir les catalogues concurrents

    Tout est stocké en JSON pour éviter une nouvelle table.
    Pour un PFE c'est la solution la plus simple.
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
    ) -> dict:
        ids = _normalize_ids(product_ids)

        if not ids:
            raise ValueError("Sélectionne au moins un produit à scraper.")

        dt = _parse_datetime(run_at)

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
            return self.state["product_jobs"].get(job_id)

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

            return job

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
                        raise Exception(result.get("error", "Erreur scraping inconnue"))

                    summary = result.get("summary", {}) or {}

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

            with self.lock:
                job = self.state["product_jobs"][job_id]
                job["status"] = "DONE" if job["failed"] == 0 else "DONE_WITH_ERRORS"
                job["finished_at"] = _iso(_now())
                self._save()

        except Exception as exc:
            with self.lock:
                job = self.state["product_jobs"].get(job_id)

                if job:
                    job["status"] = "FAILED"
                    job["finished_at"] = _iso(_now())
                    job["error"] = str(exc)
                    self._save()

        finally:
            with self.lock:
                self.running_product_job_ids.discard(job_id)

    # ------------------------------------------------------------------
    # Catalog frequency
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

    def run_catalog_now(self) -> dict:
        self._launch_catalog_thread(trigger="manual")
        return self.get_catalog_frequency()

    def _launch_catalog_thread(self, trigger: str = "scheduled"):
        with self.lock:
            if self.catalog_running:
                return

            self.catalog_running = True

            config = self.state["catalog_frequency"]
            config["last_status"] = "RUNNING"
            config["last_error"] = None
            config["last_run_at"] = _iso(_now())
            config["current_run"] = {
                "trigger": trigger,
                "status": "RUNNING",
                "started_at": _iso(_now()),
                "finished_at": None,
                "competitor_id": config.get("competitor_id"),
            }
            self._save()

        thread = threading.Thread(
            target=self._run_catalog_scraping,
            args=(trigger,),
            daemon=True,
        )
        thread.start()

    def _run_catalog_scraping(self, trigger: str = "scheduled"):
        scraper = ScrapingService()

        try:
            with self.lock:
                config = self.state["catalog_frequency"]
                competitor_id = config.get("competitor_id")

            result = scraper.scrape_due_or_all(competitor_id=competitor_id)

            with self.lock:
                config = self.state["catalog_frequency"]
                config["last_status"] = "DONE"
                config["last_finished_at"] = _iso(_now())
                config["current_run"] = {
                    **(config.get("current_run") or {}),
                    "status": "DONE",
                    "finished_at": _iso(_now()),
                    "result": result,
                }
                config["runs_history"] = [
                    config["current_run"],
                    *(config.get("runs_history") or []),
                ][:20]

                if config.get("enabled"):
                    config["next_run_at"] = _iso(
                        _now() + timedelta(minutes=int(config.get("interval_minutes") or 360))
                    )

                self._save()

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

                if config.get("enabled"):
                    config["next_run_at"] = _iso(
                        _now() + timedelta(minutes=int(config.get("interval_minutes") or 360))
                    )

                self._save()

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
