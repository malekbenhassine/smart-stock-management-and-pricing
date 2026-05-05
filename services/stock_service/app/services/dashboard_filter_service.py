from __future__ import annotations

from typing import Any


class DashboardFilterService:
    """Nettoyage centralisé des filtres dashboard.

    La période réelle n'est pas calculée ici avec date.today().
    Elle est résolue dans DashboardMetricsService à partir de MAX(date) en base.
    """

    DEFAULT_DAYS = 30
    MAX_DAYS = 365

    @classmethod
    def normalize(cls, params: dict[str, Any] | None) -> dict[str, Any]:
        params = params or {}
        raw_period = params.get("period_days", cls.DEFAULT_DAYS)

        try:
            days = int(raw_period or cls.DEFAULT_DAYS)
        except (TypeError, ValueError):
            days = cls.DEFAULT_DAYS

        days = max(1, min(days, cls.MAX_DAYS))

        return {
            "period_days": days,
            "categorie": cls.clean(params.get("categorie")),
            "marque": cls.clean(params.get("marque")),
            "statut_stock": cls.clean(params.get("statut_stock")),
            "statut_promotion": cls.clean(params.get("statut_promotion")),
            "position_marche": cls.clean(params.get("position_marche")),
        }

    @staticmethod
    def clean(value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        if not value or value.lower() in {"all", "tous", "toutes", "null", "none", "undefined"}:
            return None
        return value
