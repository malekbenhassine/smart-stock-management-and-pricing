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
LEGACY_CATALOG_INTERVAL_MINUTES = 1440  # conservé pour compatibilité, non utilisé comme fréquence métier
CATALOG_DB_SYNC_SECONDS = 60
ALLOWED_CATALOG_FREQUENCY_HOURS = {6, 12, 24}
DEFAULT_CATALOG_FREQUENCY_HOURS = 24

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

    concurrent_name = _resolve_competitor_name(row)

    produit_scrape = row.get("produitScrape") or row.get("produit_scrape") or {
        "id": row.get("id"),
        "nomProduit": _first_value(row, ["nomProduit", "nom_produit", "name", "title"]),
        "skuConcurrent": _first_value(row, ["skuConcurrent", "sku_concurrent"]),
        "urlProduit": _first_value(row, ["urlProduit", "url_produit", "url"]),
        "prixConcurrent": _first_value(row, ["prixConcurrent", "prix_concurrent", "price"]),
        "ancienPrixConcurrent": _first_value(row, ["ancienPrixConcurrent", "ancien_prix_concurrent", "old_price"]),
        "isPromo": _first_value(row, ["isPromo", "is_promo"], False),
        "disponibilite": _first_value(row, ["disponibilite", "availability"]),
        "concurrent": concurrent_name,
        "competitor_name": concurrent_name,
        "concurrent_name": concurrent_name,
        "nomConcurrent": concurrent_name,
        "concurrentId": _first_value(row, ["concurrentId", "concurrent_id", "competitor_id", "competitorId"]),
    }

    if isinstance(produit_scrape, dict):
        concurrent_name = concurrent_name or _resolve_competitor_name(produit_scrape)
        if concurrent_name:
            produit_scrape = dict(produit_scrape)
            produit_scrape["concurrent"] = concurrent_name
            produit_scrape["competitor_name"] = concurrent_name
            produit_scrape["concurrent_name"] = concurrent_name
            produit_scrape["nomConcurrent"] = concurrent_name

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
        "concurrent": concurrent_name,
        "competitor_name": concurrent_name,
        "concurrent_name": concurrent_name,
        "nomConcurrent": concurrent_name,
        "concurrentId": produit_scrape.get("concurrentId") or row.get("concurrentId") or row.get("concurrent_id") or row.get("competitor_id") or row.get("competitorId"),
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
    # invalid_items restent disponibles dans result pour diagnostic,
    # mais ne sont pas affichés comme produits à valider.

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


def _model_to_dict(obj: Any) -> dict:
    """
    Convertit un modèle Pydantic / objet simple / dict en dictionnaire.
    Utile pour lire les concurrents retournés par stock_client.get_competitors().
    """
    if obj is None:
        return {}

    if isinstance(obj, dict):
        return obj

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass

    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass

    data = {}
    for key in [
        "id",
        "nom",
        "name",
        "siteUrl",
        "site_url",
        "siteHostNormalized",
        "site_host_normalized",
    ]:
        if hasattr(obj, key):
            try:
                data[key] = getattr(obj, key)
            except Exception:
                pass

    return data


def _build_competitor_name_map(stock_client: StockServiceClient | None = None) -> dict[int, str]:
    """
    Récupère les noms depuis stock_service /competitors.
    La table réelle est :
    - concurrents.id
    - concurrents.nom

    Si l'appel échoue, on retourne {} pour ne jamais casser le scraping.
    """
    try:
        client = stock_client or StockServiceClient()
        competitors = client.get_competitors()
    except Exception as exc:
        print(f"[dual-scheduler] Impossible de charger les concurrents: {exc}")
        return {}

    mapping: dict[int, str] = {}

    for competitor in competitors or []:
        data = _model_to_dict(competitor)

        try:
            competitor_id = int(data.get("id"))
        except Exception:
            continue

        name = (
            data.get("nom")
            or data.get("name")
            or data.get("siteHostNormalized")
            or data.get("site_host_normalized")
            or data.get("siteUrl")
            or data.get("site_url")
        )

        if name:
            mapping[competitor_id] = str(name)

    return mapping


def _resolve_competitor_name(row: dict, competitor_names: dict[int, str] | None = None) -> str | None:
    """
    Résout le nom du concurrent avec plusieurs fallbacks :
    1. champs déjà présents dans la ligne ;
    2. objet concurrent imbriqué ;
    3. table concurrents via concurrent_id.
    """
    if not isinstance(row, dict):
        return None

    direct = _first_value(row, [
        "concurrent",
        "competitor_name",
        "concurrent_name",
        "nomConcurrent",
        "concurrentName",
        "site",
        "source",
    ])

    if direct:
        return str(direct)

    nested = row.get("competitor") or row.get("concurrent_obj") or row.get("concurrentData")
    if isinstance(nested, dict):
        nested_name = _first_value(nested, ["nom", "name", "siteUrl", "siteHostNormalized"])
        if nested_name:
            return str(nested_name)

    competitor_id = _first_value(row, [
        "concurrentId",
        "concurrent_id",
        "competitor_id",
        "competitorId",
    ])

    try:
        competitor_id_int = int(competitor_id)
    except Exception:
        competitor_id_int = None

    if competitor_id_int is not None and competitor_names:
        return competitor_names.get(competitor_id_int)

    return None


def _enrich_competitor_names(rows: list, competitor_names: dict[int, str] | None = None) -> list:
    """
    Ajoute les champs attendus par le front :
    - concurrent
    - competitor_name
    - concurrent_name
    - nomConcurrent

    Et les mêmes champs dans produitScrape / produit_scrape.
    """
    enriched: list = []

    for row in rows or []:
        if not isinstance(row, dict):
            enriched.append(row)
            continue

        item = dict(row)
        name = _resolve_competitor_name(item, competitor_names)

        produit_scrape = item.get("produitScrape") or item.get("produit_scrape")
        if isinstance(produit_scrape, dict):
            nested_name = _resolve_competitor_name(produit_scrape, competitor_names)
            name = name or nested_name

        if name:
            item["concurrent"] = name
            item["competitor_name"] = name
            item["concurrent_name"] = name
            item["nomConcurrent"] = name

            if isinstance(produit_scrape, dict):
                produit_scrape = dict(produit_scrape)
                produit_scrape["concurrent"] = name
                produit_scrape["competitor_name"] = name
                produit_scrape["concurrent_name"] = name
                produit_scrape["nomConcurrent"] = name
                item["produitScrape"] = produit_scrape
                item["produit_scrape"] = produit_scrape

        enriched.append(item)

    return enriched


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

    L'état détaillé des jobs est sauvegardé dans un fichier JSON.
    La configuration minimale du scraping catalogue (enabled, interval_minutes,
    competitor_id, next_run_at) est persistée en base via stock_service.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.running_product_job_ids: set[str] = set()
        self.catalog_running = False
        self._last_catalog_db_sync_monotonic = 0.0

        self.state: dict[str, Any] = {
            "product_jobs": {},
            "catalog_frequency": {
                "enabled": False,
                "interval_minutes": LEGACY_CATALOG_INTERVAL_MINUTES,
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
        self._sync_catalog_frequency_from_db(force=True)

    # ------------------------------------------------------------------
    # Persistence DB minimale de la configuration catalogue
    # ------------------------------------------------------------------
    def _catalog_db_payload(self, config: dict | None = None) -> dict:
        config = config or self.state.get("catalog_frequency", {}) or {}
        return {
            "enabled": bool(config.get("enabled")),
            # Champ legacy conservé pour compatibilité. La vraie fréquence vient du concurrent.
            "interval_minutes": int(config.get("interval_minutes") or LEGACY_CATALOG_INTERVAL_MINUTES),
            "competitor_id": config.get("competitor_id"),
            "next_run_at": config.get("next_run_at"),
        }

    def _normalize_competitor_frequency_hours(self, value: Any) -> int:
        try:
            frequency = int(value)
        except Exception:
            frequency = DEFAULT_CATALOG_FREQUENCY_HOURS

        return frequency if frequency in ALLOWED_CATALOG_FREQUENCY_HOURS else DEFAULT_CATALOG_FREQUENCY_HOURS

    def _parse_optional_competitor_datetime(self, competitor: Any, field_names: list[str]) -> datetime | None:
        for field_name in field_names:
            value = getattr(competitor, field_name, None)
            if not value:
                continue
            try:
                return _parse_datetime(str(value))
            except Exception:
                continue
        return None

    def _compute_competitor_next_scraping_at(self, competitor: Any) -> datetime | None:
        """
        Calcule le prochain scraping d'un seul concurrent.

        Règle métier :
        - déjà scrapé : dernier_scraping + fréquence ;
        - jamais scrapé : date_creation + fréquence.

        Donc un concurrent ajouté maintenant avec une fréquence de 6h
        ne part pas tout de suite : il part dans 6h.
        """
        frequency = self._normalize_competitor_frequency_hours(
            getattr(competitor, "frequence_scraping_heures", DEFAULT_CATALOG_FREQUENCY_HOURS)
        )

        base_dt = self._parse_optional_competitor_datetime(
            competitor,
            ["dernier_scraping"],
        )

        if base_dt is None:
            base_dt = self._parse_optional_competitor_datetime(
                competitor,
                ["date_creation", "created_at"],
            )

        if base_dt is None:
            # Par sécurité, si la date de création n'est pas remontée par l'API,
            # on planifie après la fréquence au lieu de lancer immédiatement.
            base_dt = _now()

        return base_dt + timedelta(hours=frequency)

    def _compute_next_catalog_job(self, competitor_id: int | None = None) -> dict | None:
        """
        Retourne le prochain concurrent à scraper et son heure exacte.

        Important : on ne retourne qu'UN seul concurrent.
        Si plusieurs concurrents sont échus, ils seront traités un par un,
        chacun dans un run séparé.
        """
        try:
            competitors = StockServiceClient().get_competitors()
        except Exception as exc:
            print(f"[dual-scheduler] Impossible de calculer le prochain scraping: {exc}", flush=True)
            return None

        candidates: list[dict] = []

        for competitor in competitors:
            current_id = int(getattr(competitor, "id", 0) or 0)

            if competitor_id is not None and current_id != int(competitor_id):
                continue

            if getattr(competitor, "actif", True) is False:
                continue

            discovery_status = str(getattr(competitor, "discovery_status", "") or "").lower()
            if discovery_status and discovery_status not in {"ready", "partial"}:
                continue

            next_at = self._compute_competitor_next_scraping_at(competitor)
            if next_at is None:
                continue

            candidates.append({
                "competitor_id": current_id,
                "competitor_name": getattr(competitor, "nom", None),
                "next_at": next_at,
            })

        if not candidates:
            return None

        return min(candidates, key=lambda item: item["next_at"])

    def _compute_next_catalog_due_at(self, competitor_id: int | None = None) -> datetime | None:
        job = self._compute_next_catalog_job(competitor_id=competitor_id)
        return job.get("next_at") if job else None

    def _get_due_catalog_competitor_id(self, competitor_id: int | None = None) -> int | None:
        job = self._compute_next_catalog_job(competitor_id=competitor_id)
        if not job:
            return None

        next_at = job.get("next_at")
        if not isinstance(next_at, datetime) or next_at > _now():
            return None

        return int(job.get("competitor_id"))

    def _refresh_next_catalog_run_at(self, persist_to_db: bool = False) -> str | None:
        with self.lock:
            config = self.state["catalog_frequency"]
            enabled = bool(config.get("enabled"))
            competitor_id = config.get("competitor_id")
            existing_next_run_at = config.get("next_run_at")
            last_status = str(config.get("last_status") or "").upper()

        # Après un échec, on garde le délai de retry déjà enregistré
        # pour éviter de relancer immédiatement le même scraping en boucle.
        if enabled and last_status == "FAILED" and existing_next_run_at:
            try:
                if _parse_datetime(existing_next_run_at) > _now():
                    return existing_next_run_at
            except Exception:
                pass

        next_due = self._compute_next_catalog_due_at(competitor_id=competitor_id) if enabled else None
        next_due_iso = _iso(next_due) if next_due else None

        with self.lock:
            config = self.state["catalog_frequency"]
            if config.get("next_run_at") != next_due_iso:
                config["next_run_at"] = next_due_iso
                self._save()
                payload = self._catalog_db_payload(config)
            else:
                payload = None

        if persist_to_db and payload:
            self._save_catalog_frequency_to_db(payload)

        return next_due_iso

    def _save_catalog_frequency_to_db(self, payload: dict | None = None) -> None:
        """
        Sauvegarde uniquement les champs nécessaires dans la base via stock_service.
        Le JSON reste utilisé pour les jobs, l'historique et le résultat du dernier run.
        """
        try:
            StockServiceClient().save_catalog_frequency_config(
                payload or self._catalog_db_payload()
            )
        except Exception as exc:
            # On ne bloque pas le scraping si stock_service est momentanément indisponible.
            print(
                f"[dual-scheduler] Configuration catalogue non sauvegardée en base: {exc}",
                flush=True,
            )

    def _sync_catalog_frequency_from_db(self, force: bool = False) -> None:
        """
        Recharge périodiquement la configuration minimale depuis la base.
        Cela permet de garder enabled=True même après rebuild / redémarrage Docker.
        """
        now_monotonic = time.monotonic()
        if not force and (
            now_monotonic - self._last_catalog_db_sync_monotonic
            < CATALOG_DB_SYNC_SECONDS
        ):
            return

        self._last_catalog_db_sync_monotonic = now_monotonic

        try:
            db_config = StockServiceClient().get_catalog_frequency_config()
        except Exception as exc:
            print(
                f"[dual-scheduler] Configuration catalogue non chargée depuis la base: {exc}",
                flush=True,
            )
            return

        if not isinstance(db_config, dict):
            return

        save_back_to_db = False
        payload_to_save = None

        with self.lock:
            config = self.state["catalog_frequency"]
            config["enabled"] = bool(db_config.get("enabled"))
            config["interval_minutes"] = int(db_config.get("interval_minutes") or LEGACY_CATALOG_INTERVAL_MINUTES)
            config["competitor_id"] = db_config.get("competitor_id")
            config["next_run_at"] = db_config.get("next_run_at")
            self._save()

        # Dès que la configuration est chargée, le prochain lancement est recalculé
        # à partir de concurrents.frequenceScrapingHeures.
        self._refresh_next_catalog_run_at(persist_to_db=True)

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

                # Si le service redémarre pendant un scraping produit, le thread
                # Python précédent n'existe plus. On évite donc de garder un job
                # bloqué visuellement en RUNNING / En cours.
                changed = False
                for product_job in self.state["product_jobs"].values():
                    if product_job.get("status") in ("RUNNING", "CANCEL_REQUESTED"):
                        product_job["status"] = "FAILED"
                        product_job["finished_at"] = _iso(_now())
                        product_job["error"] = (
                            "Le service a redémarré pendant l'exécution du scraping produit."
                        )
                        product_job["cancel_requested"] = False
                        changed = True

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
                    changed = True

                if changed:
                    self._save()

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
        launched_by_user_id: int | None = None,
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
            "launched_by_user_id": launched_by_user_id,
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

            # Avant : le backend refusait l'annulation d'un job RUNNING.
            # Maintenant : on marque le job comme annulé et le worker vérifie
            # ce flag avant d'enregistrer de nouveaux résultats.
            job["cancel_requested"] = True
            job["status"] = "CANCELLED"
            job["finished_at"] = _iso(_now())
            job["error"] = "Scraping annulé par l'utilisateur."
            self._save()

            return dict(job)

    def _is_product_job_cancelled(self, job_id: str) -> bool:
        with self.lock:
            job = self.state["product_jobs"].get(job_id)
            return bool(
                not job
                or job.get("cancel_requested")
                or job.get("status") == "CANCELLED"
            )

    def run_product_job_now(
        self,
        product_ids: list[int],
        fast: bool = True,
        debug: bool = False,
        launched_by_user_id: int | None = None,
    ) -> dict:
        job = self.create_product_job(
            product_ids=product_ids,
            run_at=_iso(_now()),
            fast=fast,
            debug=debug,
            title="Scraping immédiat produits sélectionnés",
            allow_past=True,
            launched_by_user_id=launched_by_user_id,
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
        competitor_names = _build_competitor_name_map(stock_client)

        try:
            with self.lock:
                job = self.state["product_jobs"].get(job_id)

                if not job:
                    return

                if job.get("cancel_requested") or job.get("status") == "CANCELLED":
                    job["status"] = "CANCELLED"
                    job["finished_at"] = job.get("finished_at") or _iso(_now())
                    self._save()
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
                if self._is_product_job_cancelled(job_id):
                    return

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

                    # Si l'utilisateur a annulé pendant que la recherche était
                    # en cours, on n'enregistre pas le résultat et on sort.
                    if self._is_product_job_cancelled(job_id):
                        return

                    summary = result.get("summary", {}) or {}
                    scraped_products = result.get("scraped_products", []) or result.get("saved_items", []) or []
                    scraped_products = _enrich_competitor_names(scraped_products, competitor_names)
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
                    try:
                        stock_client.mark_competitive_analysis_finished(
                            product_id=int(product_id),
                            status="DONE",
                            products_saved=int(item.get("products_saved") or 0),
                            matched=int(item.get("matched") or 0),
                            manual_review=int(item.get("manual_review") or 0),
                            ignored=int(item.get("ignored") or 0),
                        )
                    except Exception as sync_exc:
                        print(
                            f"[dual-scheduler] Impossible de synchroniser la fin d'analyse concurrentielle "
                            f"pour produit {product_id}: {sync_exc}",
                            flush=True,
                        )

                    with self.lock:
                        job = self.state["product_jobs"][job_id]
                        job["processed"] += 1
                        job["done"] += 1
                        job["items"].append(item)
                        self._save()

                    # Le produit ajouté/importé ne doit sortir de RUNNING qu'après
                    # la fin réelle du scraping et l'enregistrement des résultats.
                    try:
                        stock_client.mark_product_competitive_analysis_finished(
                            product_id=int(product_id),
                            status="DONE",
                            products_saved=int(item.get("products_saved") or 0),
                            matched=int(item.get("matched") or 0),
                            manual_review=int(item.get("manual_review") or 0),
                            ignored=int(item.get("ignored") or 0),
                        )
                    except Exception as finish_exc:
                        print(
                            f"[dual-scheduler] Statut analyse concurrentielle non mis à jour pour produit {product_id}: {finish_exc}",
                            flush=True,
                        )

                    # La recommandation concurrentielle devient prête seulement
                    # après le scraping du produit et l'enregistrement des résultats.
                    if int(item.get("matched") or 0) > 0 or int(item.get("products_saved") or 0) > 0:
                        try:
                            stock_client.trigger_price_recommendation_ready_alert(int(product_id))
                        except Exception as alert_exc:
                            print(
                                f"[dual-scheduler] Alerte recommandation prix non envoyée pour produit {product_id}: {alert_exc}",
                                flush=True,
                            )

                except Exception as exc:
                    item = {
                        "product_id": product_id,
                        "sku": product.get("sku"),
                        "nom": product.get("nom") or product.get("name"),
                        "status": "FAILED",
                        "error": str(exc),
                    }
                    try:
                        stock_client.mark_competitive_analysis_finished(
                            product_id=int(product_id),
                            status="FAILED",
                            error=str(exc),
                        )
                    except Exception as sync_exc:
                        print(
                            f"[dual-scheduler] Impossible de synchroniser l'échec d'analyse concurrentielle "
                            f"pour produit {product_id}: {sync_exc}",
                            flush=True,
                        )

                    with self.lock:
                        job = self.state["product_jobs"][job_id]
                        job["processed"] += 1
                        job["failed"] += 1
                        job["items"].append(item)
                        self._save()

                    try:
                        stock_client.mark_product_competitive_analysis_finished(
                            product_id=int(product_id),
                            status="FAILED",
                            error=str(exc),
                        )
                    except Exception as finish_exc:
                        print(
                            f"[dual-scheduler] Statut FAILED non mis à jour pour produit {product_id}: {finish_exc}",
                            flush=True,
                        )

            final_job = None
            with self.lock:
                job = self.state["product_jobs"][job_id]

                if job.get("cancel_requested") or job.get("status") == "CANCELLED":
                    job["status"] = "CANCELLED"
                    job["finished_at"] = job.get("finished_at") or _iso(_now())
                    self._save()
                    return

                job["status"] = "DONE" if job["failed"] == 0 else "DONE_WITH_ERRORS"
                job["finished_at"] = _iso(_now())
                all_scraped_items = []
                for product_item in job.get("items", []) or []:
                    all_scraped_items.extend(product_item.get("validation_items", []) or product_item.get("items", []) or [])
                job["scraped_items"] = all_scraped_items
                job["validation_items"] = [item for item in all_scraped_items if item.get("actionRequired") or item.get("canValidate")]
                final_job = dict(job)
                self._save()

            manual_count = len((final_job or {}).get("validation_items", []) or [])
            saved_count = sum(
                int(item.get("products_saved") or 0)
                for item in (final_job or {}).get("items", [])
                if isinstance(item, dict)
            )

            alerts.scraping_success(
                user_id=(final_job or {}).get("launched_by_user_id"),
                job_id=job_id,
                value=saved_count,
                message=(
                    f"Scraping produit terminé : "
                    f"{(final_job or {}).get('done', 0)} produit(s) traité(s), "
                    f"{saved_count} résultat(s) enregistré(s)."
                ),
            )

            alerts.competitor_products_to_validate(
                user_id=(final_job or {}).get("launched_by_user_id"),
                job_id=job_id,
                count=manual_count,
            )

        except Exception as exc:
            with self.lock:
                job = self.state["product_jobs"].get(job_id)

                if job:
                    job["status"] = "FAILED"
                    job["finished_at"] = _iso(_now())
                    job["error"] = str(exc)
                    self._save()

            alerts.scraping_failed(
                user_id=(job or {}).get("launched_by_user_id") if job else None,
                job_id=job_id,
                error=str(exc),
            )

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
        # interval_minutes est conservé uniquement pour compatibilité API.
        # La fréquence réelle est définie lors de l'ajout/modification du concurrent.
        interval = int(interval_minutes or LEGACY_CATALOG_INTERVAL_MINUTES)

        with self.lock:
            config = self.state["catalog_frequency"]

            config["enabled"] = bool(enabled)
            config["interval_minutes"] = interval
            config["competitor_id"] = competitor_id
            config["next_run_at"] = None
            self._save()

        self._refresh_next_catalog_run_at(persist_to_db=False)

        with self.lock:
            config = self.state["catalog_frequency"]
            result = dict(config)
            db_payload = self._catalog_db_payload(config)

        self._save_catalog_frequency_to_db(db_payload)
        return result

    def get_catalog_frequency(self) -> dict:
        self._sync_catalog_frequency_from_db(force=False)
        with self.lock:
            return dict(self.state["catalog_frequency"])

    def run_catalog_now(self, competitor_id: int | None = None, launched_by_user_id: int | None = None,) -> dict:
        """
        Lance le scraping catalogue en arrière-plan.

        Important :
        Cette fonction ne doit jamais appeler directement scrape_due_or_all().
        Elle crée seulement un thread puis retourne l'état courant.
        """
        self._launch_catalog_thread(
            trigger="manual",
            competitor_id_override=competitor_id,
            launched_by_user_id=launched_by_user_id
        )

        return self.get_catalog_frequency()

    def _launch_catalog_thread(
        self,
        trigger: str = "scheduled",
        competitor_id_override: int | None = None,
        launched_by_user_id: int | None = None,
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
                "launched_by_user_id": launched_by_user_id,
            }

            self._save()

        thread = threading.Thread(
            target=self._run_catalog_scraping,
            args=(trigger, competitor_id_override, launched_by_user_id),
            daemon=True,
        )

        thread.start()

    def _run_catalog_scraping(
        self,
        trigger: str = "scheduled",
        competitor_id_override: int | None = None,
        launched_by_user_id: int | None = None,
    ):
        scraper = ScrapingService()
        alerts = AlertClient()
        stock_client = StockServiceClient()
        competitor_names = _build_competitor_name_map(stock_client)

        try:
            with self.lock:
                config = self.state["catalog_frequency"]

                competitor_id = (
                    competitor_id_override
                    if competitor_id_override is not None
                    else config.get("competitor_id")
                )

            result = scraper.scrape_due_or_all(
                competitor_id=competitor_id,
                force_all=(trigger == "manual" and competitor_id is None),
            )
            if isinstance(result, dict):
                for key in ["items", "scraped_items", "scraped_products", "saved_items"]:
                    if isinstance(result.get(key), list):
                        result[key] = _enrich_competitor_names(result.get(key), competitor_names)
                for child in result.get("results") or []:
                    if isinstance(child, dict):
                        for key in ["items", "scraped_items", "scraped_products", "saved_items"]:
                            if isinstance(child.get(key), list):
                                child[key] = _enrich_competitor_names(child.get(key), competitor_names)

            normalized_items = _extract_catalog_items(result)
            if isinstance(result, dict):
                result["items"] = normalized_items
                result["scraped_items"] = normalized_items
                result["validation_items"] = [item for item in normalized_items if item.get("actionRequired") or item.get("canValidate")]
                result["catalog_summary"] = {
                    "total_displayed": len(normalized_items),
                    "matched": len([item for item in normalized_items if str(item.get("statutMatching") or item.get("match_status") or "").upper() == "MATCHED"]),
                    "manual_review": len([item for item in normalized_items if str(item.get("statutMatching") or item.get("match_status") or "").upper() == "MANUAL_REVIEW"]),
                    "ignored": len([item for item in normalized_items if str(item.get("statutMatching") or item.get("match_status") or "").upper() == "IGNORED"]),
                    "invalid": int(result.get("invalid", 0) or 0),
                }

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

                self._save()

            self._refresh_next_catalog_run_at(persist_to_db=True)

            manual_count = len([
            item for item in normalized_items
            if item.get("actionRequired") or item.get("canValidate")
            ])

            alerts.scraping_success(
                user_id=launched_by_user_id,
                job_id=f"catalog-{trigger}",
                value=len(normalized_items),
                message=f"Scraping catalogue terminé : {len(normalized_items)} produit(s) collecté(s).",
            )

            alerts.competitor_products_to_validate(
                user_id=launched_by_user_id,
                job_id=f"catalog-{trigger}",
                count=manual_count,
            )

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
                    # En cas d'échec, on évite une boucle immédiate infinie.
                    # Le scheduler réessaiera au prochain cycle de vérification.
                    config["next_run_at"] = _iso(_now() + timedelta(minutes=60))

                self._save()
                db_payload = self._catalog_db_payload(config)

            self._save_catalog_frequency_to_db(db_payload)

            alerts.scraping_failed(
                user_id=launched_by_user_id,
                job_id=f"catalog-{trigger}",
                error=str(exc),
            )

        finally:
            with self.lock:
                self.catalog_running = False

    # ------------------------------------------------------------------
    # Main worker
    # ------------------------------------------------------------------
    def tick(self):
        self._sync_catalog_frequency_from_db(force=False)
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

        # Scraping catalogues/sites : la fréquence est définie par concurrent
        # (6h, 12h ou 24h), pas par une fréquence globale.
        with self.lock:
            config = self.state["catalog_frequency"]
            enabled = bool(config.get("enabled"))

        if enabled and not self.catalog_running:
            next_run_at = self._refresh_next_catalog_run_at(persist_to_db=True)

            if next_run_at:
                try:
                    dt = _parse_datetime(next_run_at)

                    if dt <= now:
                        with self.lock:
                            selected_competitor_id = self.state["catalog_frequency"].get("competitor_id")

                        due_competitor_id = self._get_due_catalog_competitor_id(
                            competitor_id=selected_competitor_id
                        )

                        if due_competitor_id is not None:
                            self._launch_catalog_thread(
                                trigger="scheduled",
                                competitor_id_override=due_competitor_id,
                            )
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
    