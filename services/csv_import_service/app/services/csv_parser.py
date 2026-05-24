import json
import os
import re
import unicodedata
from io import BytesIO

import pandas as pd


def _normalize_name(value: str) -> str:
    """
    Normalise les noms de colonnes/fichiers sans perdre le sens.

    Exemples :
    - prixVente -> prix_vente
    - Prix Vente -> prix_vente
    - prix-vente -> prix_vente
    - catégorie -> categorie
    """
    value = str(value).strip()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = value.lower()
    value = value.replace(" ", "_").replace("/", "_").replace("-", "_").replace(".", "_")
    value = re.sub(r"[^a-z0-9_]+", "", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def _normalize_filename(filename: str) -> str:
    base = os.path.basename(str(filename))
    base = base.split("/")[-1].split("\\")[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", base)
    base = base.lower().strip()
    base = base.replace(" ", "_").replace("-", "_")
    base = re.sub(r"[^a-z0-9_.]+", "", base)
    base = re.sub(r"_+", "_", base)
    return base


def _filename_without_extension(filename: str) -> tuple[str, str]:
    base = _normalize_filename(filename)

    if "." not in base:
        return base, ""

    name, ext = base.rsplit(".", 1)
    return name, ext


TABLE_FILE_ALIASES = {
    "produits": [
        "produit",
        "produits",
        "product",
        "products",
        "article",
        "articles",
        "stock_produits",
        "liste_produits",
        "catalogue_produits",
        "products_list",
        "product_list",
        "catalogue",
    ],
    "fournisseurs": [
        "fournisseur",
        "fournisseurs",
        "supplier",
        "suppliers",
        "liste_fournisseurs",
    ],
    "commandes_fournisseurs": [
        "commandes_fournisseurs",
        "commande_fournisseur",
        "supplier_orders",
        "supplier_order",
        "orders_suppliers",
    ],
    "lignes_commandes": [
        "lignes_commandes",
        "ligne_commande",
        "supplier_order_lines",
        "order_lines",
        "purchase_order_lines",
    ],
    "ventes": [
        "ventes",
        "vente",
        "sales",
        "sale",
    ],
    "lignes_ventes": [
        "lignes_ventes",
        "ligne_vente",
        "sale_lines",
        "sales_lines",
        "details_ventes",
    ],
    "promotions": [
        "promotions",
        "promotion",
        "promos",
        "promo",
    ],
    "produit_promotion": [
        "produit_promotion",
        "produits_promotions",
        "product_promotion",
        "product_promotions",
        "produit_promo",
    ],
    "concurrents": [
        "concurrent",
        "concurrents",
        "competitor",
        "competitors",
        "liste_concurrents",
        "sites_concurrents",
    ],
    "produits_concurrents": [
        "produits_concurrents",
        "produit_concurrent",
        "competitor_products",
        "competitor_product",
        "products_competitors",
        "prix_concurrents",
    ],
    "mouvement_stock": [
        "mouvement_stock",
        "mouvements_stock",
        "stock_movement",
        "stock_movements",
        "mouvements",
        "stock_moves",
    ],
    "sales_history": [
        "sales_history",
        "historique_ventes",
        "historique_vente",
        "sales_historique",
        "ventes_historique",
        "history_sales",
        "sales_dataset",
        "dataset_sales",
        "historique",
    ],
}


# Tables longues en premier pour éviter une mauvaise détection.
# Exemple : produits_concurrents doit être détecté avant produits.
TABLE_DETECTION_ORDER = [
    "produits_concurrents",
    "commandes_fournisseurs",
    "lignes_commandes",
    "lignes_ventes",
    "produit_promotion",
    "mouvement_stock",
    "sales_history",
    "fournisseurs",
    "concurrents",
    "promotions",
    "produits",
    "ventes",
]


def _detect_table_from_filename(filename: str) -> str | None:
    """
    Accepte plusieurs noms de fichiers.

    Exemples acceptés :
    - produits.csv
    - produits_test.csv
    - import_produits_mai.xlsx
    - liste-produits.csv
    - concurrents_test.json
    - historique_ventes_2025.csv
    """
    name, _ = _filename_without_extension(filename)

    for table_name in TABLE_DETECTION_ORDER:
        aliases = TABLE_FILE_ALIASES.get(table_name, [])

        for alias in aliases:
            alias = _normalize_name(alias)

            if name == alias:
                return table_name

            if name.startswith(alias + "_"):
                return table_name

            if name.endswith("_" + alias):
                return table_name

            if f"_{alias}_" in name:
                return table_name

    return None


def _detect_table_from_columns(df: pd.DataFrame) -> str | None:
    """
    Fallback si le nom de fichier n'est pas clair.
    La détection accepte les alias français/anglais et les variantes camelCase/snake_case.
    """
    columns = {_normalize_name(c) for c in df.columns}

    product_columns = {
        "id",
        "sku",
        "reference",
        "ref",
        "code",
        "code_produit",
        "product_id",
        "produit_id",
        "nom",
        "name",
        "product_name",
        "nom_produit",
        "designation",
        "libelle",
        "titre",
        "categorie",
        "category",
        "famille",
        "famille_produit",
        "familleproduit",
        "categorie_produit",
        "product_category",
        "type_produit",
        "marque",
        "brand",
        "fabricant",
        "description",
        "prix_cout",
        "prixcout",
        "prix_achat",
        "cost",
        "cost_price",
        "purchase_price",
        "prix_vente",
        "prixvente",
        "prix",
        "price",
        "sale_price",
        "selling_price",
        "prix_public",
        "prix_ttc",
        "marge_reservee",
        "margereservee",
        "marge",
        "margin",
        "stock_disponible",
        "stockdisponible",
        "stock",
        "quantite_stock",
        "quantity",
        "inventory",
        "inventory_level",
        "stock_reserve",
        "stockreserve",
        "stock_minimum",
        "stockminimum",
        "seuil_max",
        "seuilmax",
        "seuil_min",
        "seuilmin",
        "statut",
        "status",
        "etat",
    }

    sales_history_columns = {
        "date",
        "date_vente",
        "datevente",
        "sale_date",
        "sales_date",
        "jour",
        "timestamp",
        "store_id",
        "store",
        "magasin",
        "magasin_id",
        "shop",
        "boutique",
        "product_id",
        "produit_id",
        "sku",
        "reference",
        "ref",
        "code_produit",
        "category",
        "categorie",
        "famille",
        "famille_produit",
        "familleproduit",
        "categorie_produit",
        "product_category",
        "type_produit",
        "region",
        "ville",
        "city",
        "zone",
        "sales",
        "ventes",
        "units_sold",
        "quantite_vendue",
        "quantitevendue",
        "qty_sold",
        "quantity_sold",
        "nombre_ventes",
        "price",
        "prix",
        "prix_vente",
        "prixvente",
        "sale_price",
        "selling_price",
        "stock",
        "inventory_level",
        "niveau_stock",
        "stock_disponible",
        "stockdisponible",
        "available_stock",
        "discount",
        "remise",
        "taux_remise",
        "promotion",
        "competitor_pricing",
        "prix_concurrent",
        "prixconcurrent",
        "competitor_price",
        "market_price",
        "units_ordered",
        "unites_commandees",
        "quantite_commandee",
        "ordered_units",
        "weather_condition",
        "condition_meteo",
        "meteo",
        "holiday_promotion",
        "promotion_jour_ferie",
        "promo_jour_ferie",
        "seasonality",
        "saisonnalite",
        "saison",
    }

    competitor_columns = {
        "nom",
        "siteurl",
        "site_url",
        "url_site",
        "frequencescrapingheures",
        "frequence_scraping_heures",
        "frequence",
    }

    competitor_product_columns = {
        "urlproduit",
        "url_produit",
        "skuconcurrent",
        "sku_concurrent",
        "nomproduit",
        "nom_produit",
        "prixconcurrent",
        "prix_concurrent",
        "concurrent_id",
        "produit_id",
    }

    stock_movement_columns = {
        "produit_id",
        "product_id",
        "id_produit",
        "type",
        "mouvement",
        "movement_type",
        "quantite",
        "quantity",
        "qty",
        "date_mouvement",
        "datemouvement",
        "movement_date",
        "justification",
        "motif",
        "reason",
    }

    sale_line_columns = {
        "vente_id",
        "sale_id",
        "id_vente",
        "produit_id",
        "product_id",
        "id_produit",
        "quantite",
        "quantity",
        "qty",
        "prix_vente_unitaire",
        "prixventeunitaire",
        "unit_price",
    }

    sale_columns = {
        "id",
        "date_vente",
        "datevente",
        "sale_date",
        "source",
        "canal",
        "statut",
        "status",
        "etat",
    }

    # IMPORTANT : on détecte sales_history avant produits, parce que sales_history peut contenir
    # sku/category/price/stock, qui existent aussi dans un fichier produits.
    has_date = bool(columns & {"date", "date_vente", "datevente", "sale_date", "sales_date", "jour", "timestamp"})
    has_sales_metric = bool(columns & {"sales", "ventes", "units_sold", "quantite_vendue", "qty_sold", "quantity_sold", "nombre_ventes"})
    has_product_key = bool(columns & {"product_id", "produit_id", "sku", "reference", "ref", "code_produit"})

    if has_date and has_sales_metric and has_product_key and len(columns & sales_history_columns) >= 4:
        return "sales_history"

    if len(columns & competitor_product_columns) >= 4:
        return "produits_concurrents"

    if len(columns & sale_line_columns) >= 4:
        return "lignes_ventes"

    if len(columns & stock_movement_columns) >= 3:
        return "mouvement_stock"

    if len(columns & product_columns) >= 5:
        return "produits"

    if len(columns & competitor_columns) >= 2:
        return "concurrents"

    # Ventes simple : après lignes_ventes pour éviter confusion.
    if len(columns & sale_columns) >= 3 and has_date:
        return "ventes"

    return None


def _parse_json(file_bytes: bytes, filename: str) -> pd.DataFrame:
    try:
        raw = json.loads(file_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        raw = json.loads(file_bytes.decode("utf-8-sig"))

    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        list_keys = [key for key, value in raw.items() if isinstance(value, list)]

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

    return pd.json_normalize(records)


def _parse_excel(file_bytes: bytes, filename: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(BytesIO(file_bytes), dtype=str, engine="openpyxl")
    except ImportError:
        raise ValueError(
            "Le support Excel n'est pas disponible sur le serveur. "
            "Installez la dépendance 'openpyxl'."
        )
    except Exception as exc:
        raise ValueError(f"Impossible de lire le fichier Excel '{filename}' : {str(exc)}")

    if df.empty:
        raise ValueError(f"Le fichier Excel '{filename}' est vide.")

    return df


def _parse_csv(file_bytes: bytes, filename: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(BytesIO(file_bytes), dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(BytesIO(file_bytes), dtype=str, encoding="latin1")

    if df.empty:
        raise ValueError(f"Le fichier CSV '{filename}' est vide.")

    return df


def parse_csv(file_bytes: bytes, filename: str):
    """
    Retourne : (DataFrame, table_name)

    Formats supportés :
    - .csv
    - .json
    - .xlsx
    - .xls

    Noms de fichiers acceptés :
    - produits.csv
    - produits_test.csv
    - import_produits_2026.csv
    - liste-produits.xlsx
    - concurrents_test.csv
    - historique_ventes_mai.csv

    Si le nom n'est pas reconnu, la table est détectée à partir des colonnes.
    """
    base_filename = _normalize_filename(filename)
    _, ext = _filename_without_extension(base_filename)

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

    df.columns = [_normalize_name(column) for column in df.columns]

    table_name = _detect_table_from_filename(base_filename)

    if not table_name:
        table_name = _detect_table_from_columns(df)

    if not table_name:
        accepted_examples = [
            "produits.csv",
            "produits_test.csv",
            "import_produits_mai.xlsx",
            "concurrents.csv",
            "concurrents_test.csv",
            "produits_concurrents.csv",
            "mouvements_stock.csv",
            "historique_ventes.csv",
            "sales_history.csv",
        ]

        raise ValueError(
            f"Nom de fichier non reconnu : '{filename}'. "
            "Le nom doit contenir le type de données ou les colonnes doivent être reconnaissables. "
            f"Exemples acceptés : {', '.join(accepted_examples)}"
        )

    return df, table_name
