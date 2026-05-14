from __future__ import annotations

import os
from typing import Any

import httpx


ALERTS_SERVICE_URL = os.getenv("ALERTS_SERVICE_URL", "http://alerts_service:8006").rstrip("/")
ALERTS_ENDPOINT = os.getenv("ALERTS_ENDPOINT", "/api/v1/alerts")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _extract_catalog_counts(result: dict[str, Any] | None) -> dict[str, int]:
    """
    Rend les alertes stables même si le résultat du scraping change de structure.
    """
    result = result or {}

    counters = {
        "competitors_processed": 0,
        "products_extracted": 0,
        "products_saved": 0,
        "matched": 0,
        "manual_review": 0,
        "ignored": 0,
        "errors": 0,
    }

    candidates = []
    if isinstance(result.get("results"), list):
        candidates.extend(result.get("results") or [])
    if isinstance(result.get("items"), list):
        candidates.extend(result.get("items") or [])
    if isinstance(result.get("competitors"), list):
        candidates.extend(result.get("competitors") or [])

    if candidates:
        counters["competitors_processed"] = len(candidates)

    # Compteurs globaux éventuels
    for key, target in [
        ("produits_extraits", "products_extracted"),
        ("products_extracted", "products_extracted"),
        ("produits_enregistres", "products_saved"),
        ("products_saved", "products_saved"),
        ("matched", "matched"),
        ("manual_review", "manual_review"),
        ("ignored", "ignored"),
        ("errors", "errors"),
    ]:
        counters[target] += _safe_int(result.get(key), 0)

    # Compteurs par concurrent / par item
    for item in candidates:
        if not isinstance(item, dict):
            continue
        counters["products_extracted"] += _safe_int(
            item.get("produits_extraits", item.get("products_extracted", item.get("productsFound"))),
            0,
        )
        counters["products_saved"] += _safe_int(
            item.get("produits_enregistres", item.get("products_saved", item.get("productsSaved"))),
            0,
        )
        counters["matched"] += _safe_int(item.get("matched"), 0)
        counters["manual_review"] += _safe_int(
            item.get("manual_review", item.get("manualReview")),
            0,
        )
        counters["ignored"] += _safe_int(item.get("ignored"), 0)
        if item.get("status") in {"FAILED", "ERROR", "error", "failed"} or item.get("error"):
            counters["errors"] += 1

    return counters


class AlertClient:
    """
    Client simple vers alerts_service.

    Important : on n'utilise pas l'API Gateway ici.
    Le scraping_service parle directement à alerts_service dans le réseau Docker,
    donc aucune route longue ne passe par le gateway.
    """

    def __init__(self):
        self.base_url = ALERTS_SERVICE_URL
        self.endpoint = ALERTS_ENDPOINT if ALERTS_ENDPOINT.startswith("/") else f"/{ALERTS_ENDPOINT}"
        self.timeout = float(os.getenv("ALERTS_TIMEOUT_SECONDS", "5"))

    def create_alert(
        self,
        *,
        title: str,
        message: str,
        alert_type: str = "SCRAPING",
        priority: str = "MEDIUM",
        source_service: str = "scraping_service",
        product_id: int | None = None,
        product_name: str | None = None,
        value: str | None = None,
        threshold: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "title": title,
            "message": message,
            "alert_type": alert_type,
            "priority": priority,
            "source_service": source_service,
            "product_id": product_id,
            "product_name": product_name,
            "value": value,
            "threshold": threshold,
            "metadata": metadata or {},
        }

        # Retire les champs vides pour rester compatible avec ton modèle d'alertes.
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                client.post(f"{self.base_url}{self.endpoint}", json=payload)
        except Exception as exc:
            # Une alerte ne doit jamais casser un scraping terminé.
            print(f"[alert-client] alerte non envoyée: {exc}")

    def catalog_success(self, *, trigger: str, result: dict[str, Any] | None) -> None:
        counts = _extract_catalog_counts(result)
        self.create_alert(
            title="Scraping catalogue terminé",
            message=(
                f"Scraping {trigger} terminé : "
                f"{counts['products_extracted']} produit(s) extrait(s), "
                f"{counts['products_saved']} enregistré(s), "
                f"{counts['matched']} matché(s), "
                f"{counts['manual_review']} à valider."
            ),
            alert_type="SCRAPING_SUCCESS",
            priority="LOW" if counts["errors"] == 0 else "MEDIUM",
            value=str(counts["products_saved"]),
            metadata={"trigger": trigger, "counts": counts},
        )

    def catalog_error(self, *, trigger: str, error: str) -> None:
        self.create_alert(
            title="Échec du scraping catalogue",
            message=f"Le scraping {trigger} a échoué : {error}",
            alert_type="SCRAPING_ERROR",
            priority="HIGH",
            metadata={"trigger": trigger, "error": error},
        )

    def product_job_success(self, *, job: dict[str, Any]) -> None:
        items = job.get("items") or []
        total_saved = sum(_safe_int(item.get("products_saved"), 0) for item in items if isinstance(item, dict))
        total_matched = sum(_safe_int(item.get("matched"), 0) for item in items if isinstance(item, dict))
        total_manual = sum(_safe_int(item.get("manual_review"), 0) for item in items if isinstance(item, dict))

        priority = "LOW" if _safe_int(job.get("failed"), 0) == 0 else "MEDIUM"
        alert_type = "SCRAPING_SUCCESS" if _safe_int(job.get("failed"), 0) == 0 else "SCRAPING_WARNING"

        self.create_alert(
            title="Scraping produit terminé",
            message=(
                f"Job {job.get('title') or job.get('id')} terminé : "
                f"{job.get('done', 0)} produit(s) traité(s), "
                f"{job.get('failed', 0)} erreur(s), "
                f"{total_saved} résultat(s) enregistré(s), "
                f"{total_matched} matché(s), {total_manual} à valider."
            ),
            alert_type=alert_type,
            priority=priority,
            value=str(total_saved),
            metadata={"job_id": job.get("id"), "items": items},
        )

    def product_job_error(self, *, job_id: str, error: str) -> None:
        self.create_alert(
            title="Échec du scraping produit",
            message=f"Le job produit {job_id} a échoué : {error}",
            alert_type="SCRAPING_ERROR",
            priority="HIGH",
            metadata={"job_id": job_id, "error": error},
        )
