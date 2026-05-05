from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.tables import Competitor, Product
from app.services.scraping_client import ScrapingServiceClient

logger = logging.getLogger(__name__)

# Fichier léger pour garder la configuration même après redémarrage du service.
# Si ton container est supprimé sans volume, ce fichier sera perdu. Pour un PFE, c'est suffisant.
CONFIG_FILE = Path("/app/.scheduler/scraping_scheduler_config.json")


def _now() -> datetime:
    """
    Heure locale simple UTC+1, pratique pour Tunisie.
    On garde des datetimes naïfs pour rester cohérent avec tes colonnes existantes.
    """
    return datetime.now(timezone(timedelta(hours=1))).replace(tzinfo=None)


def _serialize_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_time(value: str | None) -> tuple[int, int]:
    raw = str(value or "02:00").strip()

    if not re.match(r"^\d{2}:\d{2}$", raw):
        return 2, 0

    hour, minute = raw.split(":")
    hour = max(0, min(23, int(hour)))
    minute = max(0, min(59, int(minute)))

    return hour, minute


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


class ScrapingSchedulerManager:
    """
    Scheduler de scraping global.

    Modes :
    - daily    : chaque jour à une heure choisie, ex: 02:00
    - interval : toutes les X minutes, ex: 360

    Le run continue côté backend même si le front est fermé.
    """

    def __init__(self):
        self.enabled = False
        self.schedule_mode = "daily"
        self.run_time = "02:00"
        self.interval_minutes = 360
        self.product_limit = 50

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self.is_running = False
        self.started_at: datetime | None = None
        self.next_run_at: datetime | None = None
        self.last_run_at: datetime | None = None
        self.last_finished_at: datetime | None = None

        self.last_status = "IDLE"
        self.last_error: str | None = None

        self.current_run: dict[str, Any] | None = None
        self.runs_history: list[dict[str, Any]] = []

        self._load_config()

    # ---------------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------------
    def _load_config(self):
        try:
            if not CONFIG_FILE.exists():
                return

            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

            self.enabled = bool(data.get("enabled", self.enabled))
            self.schedule_mode = data.get("schedule_mode", self.schedule_mode)
            self.run_time = data.get("run_time", self.run_time)
            self.interval_minutes = int(data.get("interval_minutes", self.interval_minutes))
            self.product_limit = int(data.get("product_limit", self.product_limit))
        except Exception:
            logger.exception("Impossible de charger la config scraping scheduler.")

    def _save_config(self):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "enabled": self.enabled,
                "schedule_mode": self.schedule_mode,
                "run_time": self.run_time,
                "interval_minutes": self.interval_minutes,
                "product_limit": self.product_limit,
            }

            CONFIG_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Impossible de sauvegarder la config scraping scheduler.")

    def _compute_next_run_at(self) -> datetime:
        now = _now()

        if self.schedule_mode == "interval":
            return now + timedelta(minutes=max(5, int(self.interval_minutes or 360)))

        hour, minute = _parse_time(self.run_time)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if candidate <= now:
            candidate = candidate + timedelta(days=1)

        return candidate

    def update_config(
        self,
        enabled: bool | None = None,
        schedule_mode: str | None = None,
        run_time: str | None = None,
        interval_minutes: int | None = None,
        product_limit: int | None = None,
    ) -> dict:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)

            if schedule_mode in ("daily", "interval"):
                self.schedule_mode = schedule_mode

            if run_time is not None:
                hour, minute = _parse_time(run_time)
                self.run_time = f"{hour:02d}:{minute:02d}"

            if interval_minutes is not None:
                self.interval_minutes = max(5, int(interval_minutes))

            if product_limit is not None:
                self.product_limit = max(1, min(500, int(product_limit)))

            self.next_run_at = self._compute_next_run_at()
            self._save_config()

        return self.status()

    # ---------------------------------------------------------------------
    # Loop backend
    # ---------------------------------------------------------------------
    def start_loop(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self._stop_event.clear()
            self.started_at = _now()

            if self.next_run_at is None:
                self.next_run_at = self._compute_next_run_at()

            self._thread = threading.Thread(
                target=self._loop,
                name="scraping-scheduler-loop",
                daemon=True,
            )
            self._thread.start()

            logger.info("Scraping scheduler loop started.")

    def stop_loop(self):
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("Scraping scheduler loop stopped.")

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                now = _now()

                if self.enabled and self.next_run_at and now >= self.next_run_at:
                    self.run_once(
                        trigger="scheduled",
                        product_limit=self.product_limit,
                    )

                    with self._lock:
                        self.next_run_at = self._compute_next_run_at()

            except Exception as exc:
                logger.exception("Erreur boucle scheduler scraping.")
                with self._lock:
                    self.last_status = "ERROR"
                    self.last_error = str(exc)

            self._stop_event.wait(5)

    # ---------------------------------------------------------------------
    # Run
    # ---------------------------------------------------------------------
    def run_once_background(
        self,
        trigger: str = "manual",
        product_limit: int | None = None,
    ) -> dict:
        if self.is_running:
            return {
                "status": "already_running",
                "message": "Un scraping est déjà en cours.",
                "current_run": self.current_run,
            }

        thread = threading.Thread(
            target=self.run_once,
            kwargs={
                "trigger": trigger,
                "product_limit": product_limit or self.product_limit,
            },
            daemon=True,
        )
        thread.start()

        return {
            "status": "scheduled",
            "message": "Scraping lancé en arrière-plan.",
            "trigger": trigger,
            "product_limit": product_limit or self.product_limit,
        }

    def _active_competitors_count(self, db: Session) -> int:
        return db.query(Competitor).filter(Competitor.actif.is_(True)).count()

    def _products_to_scan(self, db: Session, product_limit: int) -> list[Product]:
        query = db.query(Product)

        if hasattr(Product, "statut"):
            query = query.filter(Product.statut == "actif")

        # On priorise les produits jamais scannés ou scannés il y a longtemps.
        return (
            query.order_by(
                Product.analyse_concurrentielle_date.asc().nullsfirst(),
                Product.id.desc(),
            )
            .limit(product_limit)
            .all()
        )

    def run_once(
        self,
        trigger: str = "manual",
        product_limit: int | None = None,
    ) -> dict:
        with self._lock:
            if self.is_running:
                return {
                    "status": "already_running",
                    "message": "Un scraping est déjà en cours.",
                    "current_run": self.current_run,
                }

            self.is_running = True
            self.last_status = "RUNNING"
            self.last_error = None

        product_limit = max(1, min(500, int(product_limit or self.product_limit)))
        started_at = _now()

        run = {
            "status": "RUNNING",
            "trigger": trigger,
            "started_at": _serialize_dt(started_at),
            "finished_at": None,
            "product_limit": product_limit,
            "schedule_mode": self.schedule_mode,
            "run_time": self.run_time,
            "interval_minutes": self.interval_minutes,
            "active_competitors": 0,
            "total": 0,
            "processed": 0,
            "done": 0,
            "failed": 0,
            "no_competitors": 0,
            "items": [],
        }

        with self._lock:
            self.current_run = dict(run)
            self.last_run_at = started_at

        db = SessionLocal()
        client = ScrapingServiceClient()

        try:
            active_competitors = self._active_competitors_count(db)
            run["active_competitors"] = active_competitors

            products = self._products_to_scan(db, product_limit)
            run["total"] = len(products)

            if active_competitors == 0:
                for product in products:
                    product.analyse_concurrentielle_statut = "NO_COMPETITORS"
                    product.analyse_concurrentielle_date = _now()

                    if getattr(product, "statut_prix", None) != "PRIX_VALIDE":
                        product.statut_prix = "RECOMMANDATION_PRETE"

                    run["processed"] += 1
                    run["no_competitors"] += 1
                    run["items"].append(
                        {
                            "product_id": product.id,
                            "sku": product.sku,
                            "nom": product.nom,
                            "status": "NO_COMPETITORS",
                            "message": "Aucun concurrent actif.",
                        }
                    )

                    with self._lock:
                        self.current_run = dict(run)

                db.commit()

            else:
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

                        if isinstance(scan, dict) and scan.get("status") == "error":
                            raise Exception(scan.get("error", "Erreur scraping inconnue"))

                        product.analyse_concurrentielle_statut = "DONE"
                        product.analyse_concurrentielle_date = _now()

                        if getattr(product, "statut_prix", None) != "PRIX_VALIDE":
                            product.statut_prix = "RECOMMANDATION_PRETE"

                        db.commit()

                        run["done"] += 1
                        run["processed"] += 1
                        run["items"].append(
                            {
                                "product_id": product.id,
                                "sku": product.sku,
                                "nom": product.nom,
                                "status": "DONE",
                                "scan_status": scan.get("status") if isinstance(scan, dict) else "success",
                            }
                        )

                    except Exception as exc:
                        logger.exception("Erreur scraping produit %s", product.id)

                        product.analyse_concurrentielle_statut = "FAILED"
                        product.analyse_concurrentielle_date = _now()

                        if getattr(product, "statut_prix", None) != "PRIX_VALIDE":
                            product.statut_prix = "RECOMMANDATION_PRETE"

                        db.commit()

                        run["failed"] += 1
                        run["processed"] += 1
                        run["items"].append(
                            {
                                "product_id": product.id,
                                "sku": product.sku,
                                "nom": product.nom,
                                "status": "FAILED",
                                "error": str(exc),
                            }
                        )

                    with self._lock:
                        self.current_run = dict(run)

            finished_at = _now()
            run["status"] = "DONE"
            run["finished_at"] = _serialize_dt(finished_at)

            with self._lock:
                self.current_run = dict(run)
                self.last_status = "DONE"
                self.last_finished_at = finished_at
                self.runs_history.insert(0, dict(run))
                self.runs_history = self.runs_history[:20]

            return run

        except Exception as exc:
            logger.exception("Erreur globale scraping planifié.")

            finished_at = _now()
            run["status"] = "FAILED"
            run["finished_at"] = _serialize_dt(finished_at)
            run["error"] = str(exc)

            with self._lock:
                self.current_run = dict(run)
                self.last_status = "FAILED"
                self.last_error = str(exc)
                self.last_finished_at = finished_at
                self.runs_history.insert(0, dict(run))
                self.runs_history = self.runs_history[:20]

            return run

        finally:
            db.close()

            with self._lock:
                self.is_running = False

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "schedule_mode": self.schedule_mode,
                "run_time": self.run_time,
                "interval_minutes": self.interval_minutes,
                "product_limit": self.product_limit,
                "is_running": self.is_running,
                "started_at": _serialize_dt(self.started_at),
                "next_run_at": _serialize_dt(self.next_run_at),
                "last_run_at": _serialize_dt(self.last_run_at),
                "last_finished_at": _serialize_dt(self.last_finished_at),
                "last_status": self.last_status,
                "last_error": self.last_error,
                "current_run": self.current_run,
                "runs_history": self.runs_history,
            }


scraping_scheduler_manager = ScrapingSchedulerManager()
