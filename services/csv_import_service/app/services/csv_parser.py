import json
import unicodedata
from io import BytesIO

import pandas as pd


def _normalize_name(value: str) -> str:
    value = str(value).strip()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower().replace(" ", "_").replace("/", "_").replace("-", "_")
    return value


FILE_NAME_TO_TABLE = {
    "produits.csv": "produits",
    "produits.json": "produits",
    "produits.xlsx": "produits",
    "produits.xls": "produits",

    "fournisseurs.csv": "fournisseurs",
    "fournisseurs.json": "fournisseurs",
    "fournisseurs.xlsx": "fournisseurs",
    "fournisseurs.xls": "fournisseurs",

    "commandes_fournisseurs.csv": "commandes_fournisseurs",
    "commandes_fournisseurs.json": "commandes_fournisseurs",
    "commandes_fournisseurs.xlsx": "commandes_fournisseurs",
    "commandes_fournisseurs.xls": "commandes_fournisseurs",

    "lignes_commandes.csv": "lignes_commandes",
    "lignes_commandes.json": "lignes_commandes",
    "lignes_commandes.xlsx": "lignes_commandes",
    "lignes_commandes.xls": "lignes_commandes",

    "ventes.csv": "ventes",
    "ventes.json": "ventes",
    "ventes.xlsx": "ventes",
    "ventes.xls": "ventes",

    "lignes_ventes.csv": "lignes_ventes",
    "lignes_ventes.json": "lignes_ventes",
    "lignes_ventes.xlsx": "lignes_ventes",
    "lignes_ventes.xls": "lignes_ventes",

    "promotions.csv": "promotions",
    "promotions.json": "promotions",
    "promotions.xlsx": "promotions",
    "promotions.xls": "promotions",

    "produit_promotion.csv": "produit_promotion",
    "produit_promotion.json": "produit_promotion",
    "produit_promotion.xlsx": "produit_promotion",
    "produit_promotion.xls": "produit_promotion",

    "concurrents.csv": "concurrents",
    "concurrents.json": "concurrents",
    "concurrents.xlsx": "concurrents",
    "concurrents.xls": "concurrents",

    "produits_concurrents.csv": "produits_concurrents",
    "produits_concurrents.json": "produits_concurrents",
    "produits_concurrents.xlsx": "produits_concurrents",
    "produits_concurrents.xls": "produits_concurrents",

    "mouvement_stock.csv": "mouvement_stock",
    "mouvement_stock.json": "mouvement_stock",
    "mouvement_stock.xlsx": "mouvement_stock",
    "mouvement_stock.xls": "mouvement_stock",

    "sales_history.csv": "sales_history",
    "sales_history.json": "sales_history",
    "sales_history.xlsx": "sales_history",
    "sales_history.xls": "sales_history",
}


def _parse_json(file_bytes: bytes, filename: str) -> pd.DataFrame:
    try:
        raw = json.loads(file_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        raw = json.loads(file_bytes.decode("utf-8-sig"))

    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        list_keys = [k for k, v in raw.items() if isinstance(v, list)]
        if not list_keys:
            raise ValueError(
                f"Le fichier JSON '{filename}' ne contient pas de tableau de données. "
                "Format attendu : liste ou {\"table\": [...]}."
            )
        records = raw[list_keys[0]]
    else:
        raise ValueError(f"Format JSON non supporté dans '{filename}'.")

    if not records:
        raise ValueError(f"Le fichier JSON '{filename}' est vide.")

    df = pd.json_normalize(records)
    return df.astype(str)


def _parse_excel(file_bytes: bytes, filename: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(BytesIO(file_bytes), dtype=str, engine="openpyxl")
    except ImportError:
        raise ValueError(
            "Le support Excel n'est pas disponible sur le serveur. "
            "Installez la dépendance 'openpyxl'."
        )
    except Exception as e:
        raise ValueError(f"Impossible de lire le fichier Excel '{filename}' : {str(e)}")

    if df.empty:
        raise ValueError(f"Le fichier Excel '{filename}' est vide.")

    return df


def _parse_csv(file_bytes: bytes, filename: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(BytesIO(file_bytes), dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(BytesIO(file_bytes), dtype=str, encoding="latin1")

    if df.empty:
        raise ValueError(f"Le fichier CSV '{filename}' est vide.")

    return df


def parse_csv(file_bytes: bytes, filename: str):
    """
    Retourne (DataFrame, table_name)
    Supports: .csv, .json, .xlsx, .xls
    """
    base_filename = filename.split("/")[-1].split("\\")[-1].lower()
    table_name = FILE_NAME_TO_TABLE.get(base_filename)

    if not table_name:
        raise ValueError(
            f"Nom de fichier non reconnu : '{filename}'. "
            "Formats attendus par exemple : produits.csv, produits.json, produits.xlsx"
        )

    ext = base_filename.rsplit(".", 1)[-1] if "." in base_filename else ""

    if ext == "csv":
        df = _parse_csv(file_bytes, filename)
    elif ext == "json":
        df = _parse_json(file_bytes, filename)
    elif ext in ("xlsx", "xls"):
        df = _parse_excel(file_bytes, filename)
    else:
        raise ValueError(
            f"Extension '.{ext}' non supportée. Utilisez .csv, .json, .xlsx ou .xls."
        )

    df.columns = [_normalize_name(c) for c in df.columns]
    return df, table_name