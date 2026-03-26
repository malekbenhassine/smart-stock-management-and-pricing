import pandas as pd
from io import BytesIO

# Colonnes obligatoires par type de CSV
REQUIRED_COLUMNS = {
    "products": ["product_id", "name", "current_price", "cost", "stock"],
    "sales": ["sale_id", "product_id", "timestamp", "qty", "unit_price"],
    "competitor_prices": ["product_id", "competitor_id", "competitor_price", "collected_at"],
    "product_suppliers": ["product_id", "supplier_id", "lead_time_days"],
    "promotions": ["promo_id", "product_id", "start_date", "end_date", "discount_pct"],
    "stock_movements": ["movement_id", "product_id", "movement_type", "direction", "qty", "timestamp"],
}


def detect_csv_type(columns: list[str]) -> str | None:
    """Détecte automatiquement le type de CSV à partir des colonnes."""
    cols = set(columns)
    for table, required in REQUIRED_COLUMNS.items():
        if set(required).issubset(cols):
            return table
    return None


def parse_csv(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, str]:
    """
    Lit le CSV, détecte son type, valide les colonnes.
    Retourne (dataframe, table_name) ou lève une ValueError.
    """
    try:
        df = pd.read_csv(BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f"Impossible de lire le CSV '{filename}': {e}")

    if df.empty:
        raise ValueError(f"Le fichier '{filename}' est vide.")

    # Détection automatique OU forçage via nom de fichier
    table_name = None
    for t in REQUIRED_COLUMNS:
        if t in filename.lower():
            table_name = t
            break

    if table_name is None:
        table_name = detect_csv_type(df.columns.tolist())

    if table_name is None:
        raise ValueError(
            f"Type de CSV non reconnu pour '{filename}'. "
            f"Colonnes trouvées : {df.columns.tolist()}"
        )

    # Vérification colonnes obligatoires
    missing = set(REQUIRED_COLUMNS[table_name]) - set(df.columns)
    if missing:
        raise ValueError(
            f"Colonnes manquantes pour '{table_name}': {missing}"
        )

    return df, table_name
