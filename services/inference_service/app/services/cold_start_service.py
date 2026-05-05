from app.services.stock_client import get_recent_history_from_stock_service

MIN_HISTORY_DAYS_FOR_STOCK_RECOMMENDATION = 14


def get_sales_history_status(product_id: str, limit: int = 30) -> dict:
    """
    Vérifie si un produit possède assez d'historique réel pour activer :
    - la prévision de demande
    - le risque de stock
    - la recommandation de restock

    Règle métier cold start :
    - historique < 14 jours => module stock désactivé
    - pricing concurrentiel reste disponible
    """

    rows = get_recent_history_from_stock_service(product_id=product_id, limit=limit)

    usable_rows = [
        row for row in rows
        if row.get("sales") is not None
    ]

    history_count = len(usable_rows)

    if history_count < MIN_HISTORY_DAYS_FOR_STOCK_RECOMMENDATION:
        return {
            "is_cold_start": True,
            "stock_module_enabled": False,
            "history_count": history_count,
            "required_history_days": MIN_HISTORY_DAYS_FOR_STOCK_RECOMMENDATION,
            "message": (
                "Historique de ventes insuffisant pour générer une prévision de stock fiable. "
                "Le produit est en phase de cold start. "
                "La recommandation prix reste disponible via les concurrents."
            ),
        }

    return {
        "is_cold_start": False,
        "stock_module_enabled": True,
        "history_count": history_count,
        "required_history_days": MIN_HISTORY_DAYS_FOR_STOCK_RECOMMENDATION,
        "message": "Historique suffisant pour activer les recommandations de stock.",
    }