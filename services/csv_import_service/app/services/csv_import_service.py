import asyncio
import math
import re
import unicodedata

import pandas as pd
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from .csv_parser import parse_csv
from .http_clients import (
    post_to_inference,
    post_to_stock,
    trigger_post_import_workflow,
    notify_stock_import_activity,
)
from .import_service import log_import_bulk


TABLE_TO_ENDPOINT = {
    "produits": ("/products/bulk", "stock"),
    "fournisseurs": ("/suppliers/bulk", "stock"),
    "commandes_fournisseurs": ("/supplier-orders/bulk", "stock"),
    "lignes_commandes": ("/supplier-order-lines/bulk", "stock"),
    "ventes": ("/sales/bulk", "stock"),
    "lignes_ventes": ("/sale-lines/bulk", "stock"),
    "promotions": ("/promotions/bulk", "stock"),
    "produit_promotion": ("/product-promotions/bulk", "stock"),
    "mouvement_stock": ("/stock-movements/bulk", "stock"),
    "sales_history": ("/sales-history/bulk", "stock"),
}

BLOCKED_IMPORT_TABLES = {
    "concurrents": (
        "L'import des concurrents par fichier est désactivé. "
        "Ajoutez les concurrents directement depuis l'application."
    ),
    "produits_concurrents": (
        "L'import des produits concurrents est désactivé. "
        "Ils doivent être générés automatiquement par le scraping."
    ),
}

ACCEPTED_EXTENSIONS = (".csv", ".json", ".xlsx", ".xls")
_NULL_STRINGS = {"none", "nan", "null", "n/a", "na", "undefined", ""}


def chunk_list(items: list[dict], chunk_size: int):
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


def _clean_value(value):
    if value is None:
        return None

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None

    return value


def _safe_int(value):
    if value is None:
        return None

    try:
        s = str(value).strip()

        if s.lower() in _NULL_STRINGS:
            return None

        return int(float(s))
    except Exception:
        return None


def _safe_float(value):
    if value is None:
        return None

    try:
        s = str(value).strip().replace(",", ".")

        if s.lower() in _NULL_STRINGS:
            return None

        return float(s)
    except Exception:
        return None


def _safe_str(value):
    if value is None:
        return None

    s = str(value).strip()

    if s.lower() in _NULL_STRINGS:
        return None

    return s


def _normalize_column_name(value: str) -> str:
    """
    Normalise un nom de colonne pour comparer plusieurs écritures possibles.

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
    value = value.replace("-", "_").replace("/", "_").replace(".", "_").replace(" ", "_")
    value = re.sub(r"[^a-z0-9_]+", "", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def _is_empty_value(value) -> bool:
    if value is None:
        return True

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return True

    return str(value).strip().lower() in _NULL_STRINGS




_TABLE_SCHEMA: dict[str, tuple[dict, list[str]]] = {
    "produits": (
        {
            "sku": "str",
            "nom": "str",
            "categorie": "str",
            "marque": "str",
            "description": "str",
            "prixcout": "float",
            "prixvente": "float",
            "margereservee": "float",
            "stockdisponible": "int",
            "stockreserve": "int",
            "stockminimum": "int",
            "seuilmax": "int",
            "seuilmin": "int",
            "statut": "str",
            "datedebutobservation": "str",
            "datefinobservation": "str",
        },
        ["sku", "nom"],
    ),
    "fournisseurs": (
        {
            "id": "int",
            "nom": "str",
            "tel": "str",
            "adresse": "str",
            "leadtimejours": "int",
            "scorefiabilite": "float",
        },
        ["id", "nom"],
    ),
    "commandes_fournisseurs": (
        {
            "id": "int",
            "fournisseur_id": "int",
            "idcommande": "str",
            "datecommande": "str",
            "datereceptionprevue": "str",
            "datereceptionreelle": "str",
            "statut": "str",
        },
        ["id", "fournisseur_id", "idcommande"],
    ),
    "lignes_commandes": (
        {
            "id": "int",
            "commande_id": "int",
            "produit_id": "int",
            "quantitecommandee": "int",
            "quantiterecue": "int",
            "prixachatunitaire": "float",
        },
        ["id", "commande_id", "produit_id"],
    ),
    "ventes": (
        {
            "id": "int",
            "datevente": "str",
            "source": "str",
            "statut": "str",
        },
        ["id"],
    ),
    "lignes_ventes": (
        {
            "id": "int",
            "vente_id": "int",
            "produit_id": "int",
            "quantite": "int",
            "prixventeunitaire": "float",
        },
        ["id", "vente_id", "produit_id"],
    ),
    "promotions": (
        {
            "id": "int",
            "nom": "str",
            "type": "str",
            "valeur": "float",
            "datedebut": "str",
            "datefin": "str",
            "stockminimumrequis": "int",
            "actif": "str",
            "prixpromo": "float",
        },
        ["id"],
    ),
    "produit_promotion": (
        {
            "produit_id": "int",
            "promotion_id": "int",
            "prixpromo": "float",
        },
        ["produit_id", "promotion_id"],
    ),
    "mouvement_stock": (
        {
            "produit_id": "int",
            "type": "str",
            "quantite": "int",
            "datemouvement": "str",
            "justification": "str",
        },
        ["produit_id", "type", "quantite"],
    ),
    "sales_history": (
        {
            "date": "str",
            "store_id": "str",
            "product_id": "str",
            "category": "str",
            "region": "str",
            "units_sold": "float",
            "price": "float",
            "inventory_level": "float",
            "discount": "float",
            "competitor_pricing": "float",
            "units_ordered": "float",
            "weather_condition": "str",
            "holiday_promotion": "int",
            "seasonality": "str",
        },
        ["date", "store_id", "product_id"],
    ),
}

_CONVERTERS = {
    "int": _safe_int,
    "float": _safe_float,
    "str": _safe_str,
}


def _apply_column_aliases(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """
    Convertit les colonnes CSV vers les champs attendus par les schémas internes.

    Objectif : accepter des fichiers écrits différemment sans casser l'ancien format.
    Exemple :
    - prixVente, prix_vente, prix, price -> prixvente pour produits
    - sales, ventes, quantite_vendue -> units_sold pour sales_history
    """
    aliases_by_table = {
        "produits": {
            # Identité produit
            "id": "id",
            "sku": "sku",
            "reference": "sku",
            "ref": "sku",
            "code": "sku",
            "code_produit": "sku",
            "product_id": "sku",
            "produit_id": "sku",

            # Nom
            "nom": "nom",
            "name": "nom",
            "product_name": "nom",
            "nom_produit": "nom",
            "designation": "nom",
            "libelle": "nom",
            "titre": "nom",

            # Catégorie
            "categorie": "categorie",
            "category": "categorie",
            "famille": "categorie",
            "famille_produit": "categorie",
            "familleproduit": "categorie",
            "categorie_produit": "categorie",
            "product_category": "categorie",
            "type_produit": "categorie",

            # Marque
            "marque": "marque",
            "brand": "marque",
            "fabricant": "marque",

            # Description
            "description": "description",
            "desc": "description",
            "details": "description",

            # Prix coût
            "prixcout": "prixcout",
            "prix_cout": "prixcout",
            "prix_achat": "prixcout",
            "cout": "prixcout",
            "cost": "prixcout",
            "cost_price": "prixcout",
            "purchase_price": "prixcout",

            # Prix vente
            "prixvente": "prixvente",
            "prix_vente": "prixvente",
            "prix": "prixvente",
            "price": "prixvente",
            "sale_price": "prixvente",
            "selling_price": "prixvente",
            "prix_public": "prixvente",
            "prix_ttc": "prixvente",

            # Marge
            "margereservee": "margereservee",
            "marge_reservee": "margereservee",
            "marge": "margereservee",
            "margin": "margereservee",

            # Stock disponible
            "stockdisponible": "stockdisponible",
            "stock_disponible": "stockdisponible",
            "stock": "stockdisponible",
            "quantite_stock": "stockdisponible",
            "quantite": "stockdisponible",
            "quantity": "stockdisponible",
            "inventory": "stockdisponible",
            "inventory_level": "stockdisponible",
            "available_stock": "stockdisponible",

            # Stock réservé
            "stockreserve": "stockreserve",
            "stock_reserve": "stockreserve",
            "reserved_stock": "stockreserve",

            # Stock minimum
            "stockminimum": "stockminimum",
            "stock_minimum": "stockminimum",
            "minimum_stock": "stockminimum",
            "min_stock": "stockminimum",

            # Seuil max
            "seuilmax": "seuilmax",
            "seuil_max": "seuilmax",
            "max_stock": "seuilmax",
            "stock_max": "seuilmax",
            "stockmaximum": "seuilmax",
            "stock_maximum": "seuilmax",

            # Seuil min
            "seuilmin": "seuilmin",
            "seuil_min": "seuilmin",
            "min_stock_alert": "seuilmin",
            "seuil_alerte": "seuilmin",

            # Statut
            "statut": "statut",
            "status": "statut",
            "etat": "statut",

            # Dates observation
            "datedebutobservation": "datedebutobservation",
            "date_debut_observation": "datedebutobservation",
            "date_debut": "datedebutobservation",
            "start_date": "datedebutobservation",

            "datefinobservation": "datefinobservation",
            "date_fin_observation": "datefinobservation",
            "date_fin": "datefinobservation",
            "end_date": "datefinobservation",
        },

        "sales_history": {
            # Date
            "date": "date",
            "date_vente": "date",
            "datevente": "date",
            "sale_date": "date",
            "sales_date": "date",
            "jour": "date",
            "timestamp": "date",

            # Magasin
            "store_id": "store_id",
            "store": "store_id",
            "magasin": "store_id",
            "magasin_id": "store_id",
            "shop": "store_id",
            "boutique": "store_id",

            # Produit
            "product_id": "product_id",
            "produit_id": "product_id",
            "sku": "product_id",
            "reference": "product_id",
            "ref": "product_id",
            "code_produit": "product_id",

            # Catégorie
            "category": "category",
            "categorie": "category",
            "famille": "category",
            "famille_produit": "category",
            "familleproduit": "category",
            "categorie_produit": "category",
            "product_category": "category",
            "type_produit": "category",

            # Région
            "region": "region",
            "ville": "region",
            "city": "region",
            "zone": "region",

            # Ventes
            "sales": "units_sold",
            "units_sold": "units_sold",
            "ventes": "units_sold",
            "quantite_vendue": "units_sold",
            "quantitevendue": "units_sold",
            "qty_sold": "units_sold",
            "quantity_sold": "units_sold",
            "nombre_ventes": "units_sold",

            # Prix
            "price": "price",
            "prix": "price",
            "prix_vente": "price",
            "prixvente": "price",
            "sale_price": "price",
            "selling_price": "price",

            # Stock historique
            "stock": "inventory_level",
            "inventory_level": "inventory_level",
            "niveau_stock": "inventory_level",
            "stock_disponible": "inventory_level",
            "stockdisponible": "inventory_level",
            "available_stock": "inventory_level",

            # Remise
            "discount": "discount",
            "remise": "discount",
            "taux_remise": "discount",
            "promotion": "discount",

            # Prix concurrent
            "competitor_pricing": "competitor_pricing",
            "prix_concurrent": "competitor_pricing",
            "prixconcurrent": "competitor_pricing",
            "competitor_price": "competitor_pricing",
            "market_price": "competitor_pricing",

            # Commandes
            "units_ordered": "units_ordered",
            "unites_commandees": "units_ordered",
            "quantite_commandee": "units_ordered",
            "ordered_units": "units_ordered",

            # Météo
            "weather_condition": "weather_condition",
            "condition_meteo": "weather_condition",
            "meteo": "weather_condition",

            # Promotion jour férié
            "holiday_promotion": "holiday_promotion",
            "promotion_jour_ferie": "holiday_promotion",
            "jour_ferie_promo": "holiday_promotion",
            "promo_jour_ferie": "holiday_promotion",

            # Saison
            "seasonality": "seasonality",
            "saisonnalite": "seasonality",
            "saison": "seasonality",
        },

        "fournisseurs": {
            "id": "id",
            "nom": "nom",
            "name": "nom",
            "fournisseur": "nom",
            "supplier": "nom",
            "tel": "tel",
            "telephone": "tel",
            "phone": "tel",
            "adresse": "adresse",
            "address": "adresse",
            "leadtimejours": "leadtimejours",
            "lead_time_jours": "leadtimejours",
            "lead_time": "leadtimejours",
            "scorefiabilite": "scorefiabilite",
            "score_fiabilite": "scorefiabilite",
            "reliability_score": "scorefiabilite",
        },

        "commandes_fournisseurs": {
            "id": "id",
            "fournisseur_id": "fournisseur_id",
            "supplier_id": "fournisseur_id",
            "idcommande": "idcommande",
            "id_commande": "idcommande",
            "order_id": "idcommande",
            "datecommande": "datecommande",
            "date_commande": "datecommande",
            "order_date": "datecommande",
            "datereceptionprevue": "datereceptionprevue",
            "date_reception_prevue": "datereceptionprevue",
            "expected_receipt_date": "datereceptionprevue",
            "datereceptionreelle": "datereceptionreelle",
            "date_reception_reelle": "datereceptionreelle",
            "real_receipt_date": "datereceptionreelle",
            "statut": "statut",
            "status": "statut",
            "etat": "statut",
        },

        "lignes_commandes": {
            "id": "id",
            "commande_id": "commande_id",
            "order_id": "commande_id",
            "produit_id": "produit_id",
            "product_id": "produit_id",
            "id_produit": "produit_id",
            "quantitecommandee": "quantitecommandee",
            "quantite_commandee": "quantitecommandee",
            "ordered_quantity": "quantitecommandee",
            "quantiterecue": "quantiterecue",
            "quantite_recue": "quantiterecue",
            "received_quantity": "quantiterecue",
            "prixachatunitaire": "prixachatunitaire",
            "prix_achat_unitaire": "prixachatunitaire",
            "purchase_unit_price": "prixachatunitaire",
            "unit_cost": "prixachatunitaire",
        },

        "ventes": {
            "id": "id",
            "datevente": "datevente",
            "date_vente": "datevente",
            "date": "datevente",
            "sale_date": "datevente",
            "source": "source",
            "canal": "source",
            "channel": "source",
            "statut": "statut",
            "status": "statut",
            "etat": "statut",
        },

        "lignes_ventes": {
            "id": "id",
            "vente_id": "vente_id",
            "sale_id": "vente_id",
            "id_vente": "vente_id",
            "produit_id": "produit_id",
            "product_id": "produit_id",
            "id_produit": "produit_id",
            "quantite": "quantite",
            "quantity": "quantite",
            "qty": "quantite",
            "quantite_vendue": "quantite",
            "prixventeunitaire": "prixventeunitaire",
            "prix_vente_unitaire": "prixventeunitaire",
            "prix_unitaire": "prixventeunitaire",
            "unit_price": "prixventeunitaire",
            "price": "prixventeunitaire",
        },

        "promotions": {
            "id": "id",
            "nom": "nom",
            "name": "nom",
            "type": "type",
            "valeur": "valeur",
            "value": "valeur",
            "datedebut": "datedebut",
            "date_debut": "datedebut",
            "start_date": "datedebut",
            "datefin": "datefin",
            "date_fin": "datefin",
            "end_date": "datefin",
            "stockminimumrequis": "stockminimumrequis",
            "stock_minimum_requis": "stockminimumrequis",
            "actif": "actif",
            "active": "actif",
            "prixpromo": "prixpromo",
            "prix_promo": "prixpromo",
            "promo_price": "prixpromo",
        },

        "produit_promotion": {
            "produit_id": "produit_id",
            "product_id": "produit_id",
            "promotion_id": "promotion_id",
            "promo_id": "promotion_id",
            "prixpromo": "prixpromo",
            "prix_promo": "prixpromo",
            "promo_price": "prixpromo",
        },

        "mouvement_stock": {
            "produit_id": "produit_id",
            "product_id": "produit_id",
            "id_produit": "produit_id",
            "type": "type",
            "mouvement": "type",
            "movement_type": "type",
            "quantite": "quantite",
            "quantity": "quantite",
            "qty": "quantite",
            "datemouvement": "datemouvement",
            "date_mouvement": "datemouvement",
            "date": "datemouvement",
            "movement_date": "datemouvement",
            "justification": "justification",
            "motif": "justification",
            "reason": "justification",
        },
    }

    aliases = aliases_by_table.get(table_name, {})

    if not aliases:
        return df

    normalized_aliases = {
        _normalize_column_name(source): target
        for source, target in aliases.items()
    }

    result = pd.DataFrame(index=df.index)

    for original_column in df.columns:
        normalized_column = _normalize_column_name(original_column)
        target_column = normalized_aliases.get(normalized_column, normalized_column)

        # Si plusieurs colonnes veulent dire la même chose, on garde la première valeur non vide.
        if target_column in result.columns:
            result[target_column] = result[target_column].combine_first(df[original_column])
        else:
            result[target_column] = df[original_column]

    return result

def _normalize_rows_after_cleaning(table_name: str, rows: list[dict]) -> list[dict]:
    normalized = []

    for row in rows:
        clean_row = dict(row)

        if table_name == "produits":
            clean_row.pop("id", None)

            if not clean_row.get("sku") or not clean_row.get("nom"):
                continue

            clean_row["sku"] = str(clean_row["sku"]).strip()
            clean_row["nom"] = str(clean_row["nom"]).strip()

            if clean_row.get("statut") is None:
                clean_row["statut"] = "actif"

            if clean_row.get("stockdisponible") is None:
                clean_row["stockdisponible"] = 0

            if clean_row.get("stockreserve") is None:
                clean_row["stockreserve"] = 0

        elif table_name == "mouvement_stock":
            clean_row.pop("id", None)

        normalized.append(clean_row)

    return normalized


def _get_first_existing(row: dict, *keys):
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return None


def _clean_sales_history_row(row: dict) -> dict:
    """
    Nettoie une ligne historique avec compatibilité français/anglais.
    Le stock_service accepte les alias Pydantic anglais (store_id/product_id/sales/price),
    mais on garde aussi les champs français pour compatibilité interne.
    """
    units_sold = _safe_float(
        _get_first_existing(
            row,
            "units_sold",
            "sales",
            "ventes",
            "quantite_vendue",
            "quantity_sold",
            "qty_sold",
            "nombre_ventes",
        )
    )

    inventory_level = _safe_float(
        _get_first_existing(
            row,
            "inventory_level",
            "stock",
            "stock_disponible",
            "niveau_stock",
            "available_stock",
        )
    )

    price = _safe_float(
        _get_first_existing(
            row,
            "price",
            "prix",
            "prix_vente",
            "prixvente",
            "sale_price",
            "selling_price",
        )
    )

    store_id = _safe_str(
        _get_first_existing(
            row,
            "store_id",
            "magasin_id",
            "magasin",
            "store",
            "shop",
            "boutique",
        )
    )

    product_id = _safe_str(
        _get_first_existing(
            row,
            "product_id",
            "produit_id",
            "sku",
            "reference",
            "ref",
            "code_produit",
        )
    )

    category = _safe_str(
        _get_first_existing(
            row,
            "category",
            "categorie",
            "famille",
            "famille_produit",
            "familleproduit",
            "categorie_produit",
            "product_category",
            "type_produit",
        )
    )

    discount = _safe_float(
        _get_first_existing(
            row,
            "discount",
            "remise",
            "taux_remise",
            "promotion",
        )
    )

    competitor_pricing = _safe_float(
        _get_first_existing(
            row,
            "competitor_pricing",
            "prix_concurrent",
            "competitor_price",
            "market_price",
        )
    )

    units_ordered = _safe_float(
        _get_first_existing(
            row,
            "units_ordered",
            "unites_commandees",
            "quantite_commandee",
            "ordered_units",
        )
    )

    weather_condition = _safe_str(
        _get_first_existing(
            row,
            "weather_condition",
            "condition_meteo",
            "meteo",
        )
    )

    holiday_promotion = _safe_int(
        _get_first_existing(
            row,
            "holiday_promotion",
            "promotion_jour_ferie",
            "jour_ferie_promo",
            "promo_jour_ferie",
        )
    )

    seasonality = _safe_str(
        _get_first_existing(
            row,
            "seasonality",
            "saisonnalite",
            "saison",
        )
    )

    return {
        # Champs anglais envoyés au stock_service via alias Pydantic.
        "date": _safe_str(_get_first_existing(row, "date", "date_vente", "sale_date")),
        "store_id": store_id,
        "product_id": product_id,
        "category": category,
        "region": _safe_str(_get_first_existing(row, "region", "ville", "city", "zone")),
        "units_sold": units_sold,
        "sales": units_sold,
        "inventory_level": inventory_level,
        "stock": inventory_level,
        "price": price,
        "discount": discount,
        "competitor_pricing": competitor_pricing,
        "units_ordered": units_ordered,
        "demand_forecast": _safe_float(row.get("demand_forecast")),
        "weather_condition": weather_condition,
        "holiday_promotion": holiday_promotion,
        "seasonality": seasonality,
        "timestamp": _safe_str(row.get("timestamp")),

        # Champs français gardés pour compatibilité avec d'autres traitements.
        "magasin_id": store_id,
        "produit_id": product_id,
        "categorie": category,
        "ventes": units_sold,
        "prix": price,
        "remise": discount,
        "prix_concurrent": competitor_pricing,
        "unites_commandees": units_ordered,
        "condition_meteo": weather_condition,
        "promotion_jour_ferie": holiday_promotion,
        "saisonnalite": seasonality,
    }

def clean_records(df: pd.DataFrame, table_name: str) -> list[dict]:
    df = df.copy()
    df = _apply_column_aliases(df, table_name)
    df = df.where(pd.notnull(df), None)
    df = df.dropna(how="all")

    schema, required_fields = _TABLE_SCHEMA.get(table_name, ({}, []))

    cleaned = []

    for row in df.to_dict(orient="records"):
        if table_name == "sales_history":
            cleaned_row = _clean_sales_history_row(row)
        elif schema:
            cleaned_row = {
                field: _CONVERTERS[dtype](row.get(field))
                for field, dtype in schema.items()
            }
        else:
            cleaned_row = {k: _clean_value(v) for k, v in row.items()}

        if any(cleaned_row.get(field) is None for field in required_fields):
            continue

        cleaned.append(cleaned_row)

    return _normalize_rows_after_cleaning(table_name, cleaned)

async def _send_chunks(
    endpoint: str,
    target: str,
    rows: list[dict],
    chunk_size: int,
    max_concurrency: int = 1,
) -> tuple[int, int, list[dict], list[int]]:
    chunks = list(chunk_list(rows, chunk_size))

    if not chunks:
        return 0, 0, [], []

    post_fn = post_to_stock if target == "stock" else post_to_inference

    total_sent = 0
    responses: list[dict] = []
    product_ids: list[int] = []

    semaphore = asyncio.Semaphore(max_concurrency)

    async def send_one_chunk(chunk: list[dict]):
        async with semaphore:
            response = await post_fn(endpoint, chunk)
            return len(chunk), response

    for chunk in chunks:
        sent, response = await send_one_chunk(chunk)
        total_sent += sent

        if isinstance(response, dict):
            responses.append(response)

            ids = response.get("product_ids") or []
            if isinstance(ids, list):
                product_ids.extend(ids)

    product_ids = list(
        dict.fromkeys(
            [int(pid) for pid in product_ids if pid is not None]
        )
    )

    return total_sent, len(chunks), responses, product_ids


async def process_single_file(file_name: str, content: bytes) -> dict:
    df, table_name = parse_csv(content, file_name)

    if table_name in BLOCKED_IMPORT_TABLES:
        return {
            "status": "skipped",
            "filename": file_name,
            "table": table_name,
            "rows_imported": 0,
            "target_service": None,
            "target_response": {
                "status": "skipped",
                "rows": 0,
                "chunks": 0,
                "chunk_size": 0,
                "responses": [],
                "product_ids": [],
                "total_products_to_scan": 0,
            },
            "message": BLOCKED_IMPORT_TABLES[table_name],
            "post_import_workflow": {
                "status": "skipped",
                "reason": "Aucun workflow lancé car ce type d'import est désactivé.",
                "table": table_name,
            },
        }

    rows = clean_records(df, table_name)

    if table_name not in TABLE_TO_ENDPOINT:
        raise ValueError(f"Aucune route cible configurée pour la table '{table_name}'")

    endpoint, target = TABLE_TO_ENDPOINT[table_name]

    if table_name == "sales_history":
        chunk_size = 500
        max_concurrency = 1
    else:
        chunk_size = len(rows) or 1
        max_concurrency = 1

    total_sent, chunk_count, target_responses, product_ids = await _send_chunks(
        endpoint=endpoint,
        target=target,
        rows=rows,
        chunk_size=chunk_size,
        max_concurrency=max_concurrency,
    )

    result = {
        "status": "success",
        "filename": file_name,
        "table": table_name,
        "rows_imported": total_sent,
        "target_service": target,
        "target_response": {
            "status": "success",
            "rows": total_sent,
            "chunks": chunk_count,
            "chunk_size": chunk_size,
            "responses": target_responses,
            "product_ids": product_ids,
            "total_products_to_scan": len(product_ids),
        },
    }

    if table_name == "produits" and total_sent > 0:
        result["post_import_workflow"] = await trigger_post_import_workflow(
            table_name="produits",
            max_products=len(product_ids) or 30,
            product_ids=product_ids,
        )

    elif table_name == "produits" and total_sent == 0:
        result["post_import_workflow"] = {
            "status": "skipped",
            "reason": "Aucune ligne produit importée, scraping non lancé.",
            "table": table_name,
            "product_ids": [],
            "total_products_to_scan": 0,
        }

    else:
        result["post_import_workflow"] = {
            "status": "not_required",
            "reason": f"Aucun workflow post-import nécessaire pour la table '{table_name}'.",
            "table": table_name,
        }

    return result

async def import_single_file(file: UploadFile, db: Session, upsert: bool = False):
    filename = file.filename or ""

    if not any(filename.lower().endswith(ext) for ext in ACCEPTED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté. Formats acceptés : {', '.join(ACCEPTED_EXTENSIONS)}",
        )

    content = await file.read()

    try:
        result = await process_single_file(filename, content)

        log_import_bulk(
            db,
            [
                {
                    "filename": filename,
                    "table": result.get("table", "unknown"),
                    "status": "SUCCESS" if result.get("status") != "error" else "ERROR",
                    "rows": result.get("rows_imported", 0),
                    "error": result.get("message") if result.get("status") == "skipped" else None,
                }
            ],
        )
        if result.get("status") == "success":
            result["activity_log"] = await notify_stock_import_activity(
                {
                    "filename": filename,
                    "table": result.get("table", "unknown"),
                    "rows_imported": result.get("rows_imported", 0),
                    "target_service": result.get("target_service"),
                }
            )

        return result

    except HTTPException:
        raise

    except Exception as exc:
        log_import_bulk(
            db,
            [
                {
                    "filename": filename,
                    "table": "unknown",
                    "status": "ERROR",
                    "rows": 0,
                    "error": str(exc),
                }
            ],
        )

        raise HTTPException(status_code=500, detail=str(exc))


async def import_batch_files(files: list[UploadFile], db: Session, upsert: bool = False):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier envoyé.")

    results = []

    for file in files:
        try:
            result = await import_single_file(file, db, upsert=upsert)
            results.append(result)
        except HTTPException as exc:
            results.append(
                {
                    "status": "error",
                    "filename": file.filename,
                    "detail": exc.detail,
                }
            )

    success_count = sum(1 for r in results if r.get("status") == "success")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")
    error_count = len(results) - success_count - skipped_count

    return {
        "status": "completed",
        "total_files": len(files),
        "success_count": success_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "results": results,
    }


def get_import_logs_service(limit: int, db: Session):
    from ..models.tables import ImportLog

    return (
        db.query(ImportLog)
        .order_by(ImportLog.imported_at.desc())
        .limit(limit)
        .all()
    )