from __future__ import annotations

import os
from typing import Any

import httpx

ALERTS_SERVICE_URL = os.getenv(
    "ALERTS_SERVICE_URL",
    "http://alerts_service:8006",
).rstrip("/")

ALERTS_EVENTS_ENDPOINT = os.getenv(
    "ALERTS_EVENTS_ENDPOINT",
    "/api/v1/alerts/events",
)

ALERTS_TIMEOUT_SECONDS = float(
    os.getenv("ALERTS_TIMEOUT_SECONDS", "5")
)


def emit_alert_event(
    *,
    event_type: str,
    source_service: str,
    user_id: int | None = None,
    user_email: str | None = None,
    user_role: str | None = None,
    target_role: str | None = None,
    product_id: int | None = None,
    product_name: str | None = None,
    value: Any = None,
    threshold: Any = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    payload = {
        "event_type": event_type,
        "source_service": source_service,
        "user_id": user_id,
        "user_email": user_email,
        "user_role": user_role,
        "target_role": target_role,
        "product_id": product_id,
        "product_name": product_name,
        "value": value,
        "threshold": threshold,
        "metadata": metadata or {},
    }

    payload = {key: value for key, value in payload.items() if value is not None}

    try:
        endpoint = (
            ALERTS_EVENTS_ENDPOINT
            if ALERTS_EVENTS_ENDPOINT.startswith("/")
            else f"/{ALERTS_EVENTS_ENDPOINT}"
        )

        url = f"{ALERTS_SERVICE_URL}{endpoint}"

        print("[auth-alert-client] POST", url)
        print("[auth-alert-client] payload:", payload)

        with httpx.Client(timeout=ALERTS_TIMEOUT_SECONDS) as client:
            response = client.post(url, json=payload)

        print("[auth-alert-client] status:", response.status_code)
        print("[auth-alert-client] response:", response.text)

        return 200 <= response.status_code < 300

    except Exception as exc:
        print("[auth-alert-client] événement non envoyé:", str(exc))
        print("[auth-alert-client] payload:", payload)
        return False