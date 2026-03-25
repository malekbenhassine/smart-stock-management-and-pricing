from pathlib import Path
from typing import Dict, List
import pandas as pd

FILE_SCHEMAS: Dict[str, List[str]] = {
    "sales.csv": ["product_id", "qty", "timestamp"],
    "products.csv": ["product_id", "name", "current_price", "current_stock"],
    "competitor_prices.csv": ["product_id", "collected_at", "competitor_price"],
    "promotions.csv": ["product_id", "start_date", "end_date", "promo_price"],
    "product_suppliers.csv": ["product_id", "supplier_id", "lead_time_days"],
    "suppliers.csv": ["supplier_id", "name"],
    "competitors.csv": ["competitor_id", "name"],
    "inventory_counts.csv": ["inventory_date", "product_id", "system_qty", "physical_qty"],
    "purchase_orders.csv": ["po_id", "supplier_id", "status", "created_at"],
    "purchase_order_lines.csv": ["po_line_id", "po_id", "product_id", "qty_ordered", "unit_cost"],
    "stock_movements.csv": ["movement_id", "product_id", "qty", "timestamp"],
    "alerts.csv": ["alert_id", "alert_type", "product_id", "created_at"],
    "auth_events.csv": ["event_id", "user_id", "event_type", "timestamp"],
    "users.csv": ["user_id", "full_name", "email", "role"],
    "price_recommendations.csv": ["recommendation_id", "product_id", "recommended_price", "status"],
}

REQUIRED_FILES = {"sales.csv", "products.csv"}


class CsvValidationError(Exception):
    pass


def validate_csv_file(path: Path, filename: str) -> dict:
    if filename not in FILE_SCHEMAS:
        raise CsvValidationError(
            f"Nom de fichier non supporté: {filename}. "
            f"Fichiers supportés: {sorted(FILE_SCHEMAS.keys())}"
        )

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise CsvValidationError(f"Impossible de lire {filename}: {exc}") from exc

    if df.empty:
        raise CsvValidationError(f"Le fichier {filename} est vide.")

    required_columns = FILE_SCHEMAS[filename]
    actual_columns = [str(c) for c in df.columns.tolist()]
    missing_columns = [col for col in required_columns if col not in actual_columns]

    if missing_columns:
        raise CsvValidationError(
            f"Le fichier {filename} est invalide. "
            f"Colonnes manquantes: {missing_columns}"
        )

    return {
        "filename": filename,
        "rows": int(len(df)),
        "columns": actual_columns,
        "required_columns": required_columns,
        "missing_columns": missing_columns,
        "status": "VALID",
    }