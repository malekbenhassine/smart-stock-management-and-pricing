import pandas as pd
from io import BytesIO
import unicodedata


def _normalize_name(value: str) -> str:
    value = str(value).strip()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower().replace(" ", "_").replace("/", "_").replace("-", "_")
    return value


FILE_NAME_TO_TABLE = {
    "produits.csv": "produits",
    "fournisseurs.csv": "fournisseurs",
    "commandes_fournisseurs.csv": "commandes_fournisseurs",
    "lignes_commandes.csv": "lignes_commandes",
    "ventes.csv": "ventes",
    "lignes_ventes.csv": "lignes_ventes",
    "promotions.csv": "promotions",
    "produit_promotion.csv": "produit_promotion",
    "concurrents.csv": "concurrents",
    "produits_concurrents.csv": "produits_concurrents",
    "mouvement_stock.csv": "mouvement_stock",
    "sales_history.csv": "sales_history",
}


def parse_csv(file_bytes: bytes, filename: str):
    # Important: tout lire en texte pour éviter que pandas transforme
    # des téléphones ou SKU en nombres
    df = pd.read_csv(BytesIO(file_bytes), dtype=str)

    if df.empty:
        raise ValueError(f"Le fichier '{filename}' est vide.")

    df.columns = [_normalize_name(c) for c in df.columns]

    base_filename = filename.split("/")[-1].split("\\")[-1].lower()
    table_name = FILE_NAME_TO_TABLE.get(base_filename)

    if not table_name:
        raise ValueError(f"Nom de fichier CSV non reconnu: {filename}")

    return df, table_name