from __future__ import annotations

import os
from typing import Any
import httpx

ALERTS_SERVICE_URL = os.getenv("ALERTS_SERVICE_URL", "http://alerts_service:8006").rstrip("/")
ALERTS_ENDPOINT = os.getenv("ALERTS_ENDPOINT", "/api/v1/alerts/events")


class AlertClient:
    def __init__(self):
        self.base_url = ALERTS_SERVICE_URL
        self.endpoint = ALERTS_ENDPOINT if ALERTS_ENDPOINT.startswith("/") else f"/{ALERTS_ENDPOINT}"
        self.timeout = float(os.getenv("ALERTS_TIMEOUT_SECONDS", "5"))

    def emit(self, *, event_type: str, user_id: int | None = None, metadata: dict[str, Any] | None = None):
        payload = {"event_type": event_type, "source_service": "scraping_service", "user_id": user_id, "metadata": metadata or {}}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}{self.endpoint}", json=payload)
                print(f"[SCRAPING_ALERT] {event_type} user_id={user_id} status={response.status_code} body={response.text[:300]}", flush=True)
        except Exception as exc:
            print(f"[SCRAPING_ALERT] erreur envoi alerte: {exc}", flush=True)

    def scraping_success(self, *, user_id: int | None, job_id: str | None, message: str, value: int = 0):
        self.emit(event_type="SCRAPING_SUCCESS", user_id=user_id, metadata={"job_id": job_id, "message": message, "value": value})

    def scraping_failed(self, *, user_id: int | None, job_id: str | None, error: str):
        self.emit(event_type="SCRAPING_FAILED", user_id=user_id, metadata={"job_id": job_id, "message": f"Le scraping a échoué : {error}", "error": error})

    def competitor_products_to_validate(self, *, user_id: int | None, job_id: str | None, count: int):
        if count <= 0:
            return
        self.emit(event_type="COMPETITOR_PRODUCT_TO_VALIDATE", user_id=user_id, metadata={"job_id": job_id, "count": count, "message": f"{count} produit(s) concurrent(s) nécessitent une validation."})
