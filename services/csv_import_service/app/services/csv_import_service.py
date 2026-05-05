import asyncio
import math

import pandas as pd
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from .csv_parser import parse_csv
from .http_clients import post_to_inference, post_to_stock, trigger_post_import_workflow
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
    aliases_by_table = {
        "produits": {
            "id": "id",
            "sku": "sku",
            "reference": "sku",
            "ref": "sku",
            "nom": "nom",
            "name": "nom",
            "designation": "nom",
            "categorie": "categorie",
            "category": "categorie",
            "marque": "marque",
            "brand": "marque",
            "description": "description",
            "prixcout": "prixcout",
            "prix_cout": "prixcout",
            "prixCout": "prixcout",
            "cost_price": "prixcout",
            "prixvente": "prixvente",
            "prix_vente": "prixvente",
            "prixVente": "prixvente",
            "sale_price": "prixvente",
            "margereservee": "margereservee",
            "marge_reservee": "margereservee",
            "margeReservee": "margereservee",
            "stockdisponible": "stockdisponible",
            "stock_disponible": "stockdisponible",
            "stockDisponible": "stockdisponible",
            "stock": "stockdisponible",
            "stockreserve": "stockreserve",
            "stock_reserve": "stockreserve",
            "stockReserve": "stockreserve",
            "stockminimum": "stockminimum",
            "stock_minimum": "stockminimum",
            "stockMinimum": "stockminimum",
            "seuilmax": "seuilmax",
            "seuil_max": "seuilmax",
            "seuilMax": "seuilmax",
            "seuilmin": "seuilmin",
            "seuil_min": "seuilmin",
            "seuilMin": "seuilmin",
            "statut": "statut",
            "status": "statut",
            "datedebutobservation": "datedebutobservation",
            "date_debut_observation": "datedebutobservation",
            "dateDebutObservation": "datedebutobservation",
            "datefinobservation": "datefinobservation",
            "date_fin_observation": "datefinobservation",
            "dateFinObservation": "datefinobservation",
        }
    }

    aliases = aliases_by_table.get(table_name, {})

    if not aliases:
        return df

    rename_map = {}

    for column in df.columns:
        normalized = str(column).strip()
        target = aliases.get(normalized)

        if target:
            rename_map[column] = target

    return df.rename(columns=rename_map)


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


def clean_records(df: pd.DataFrame, table_name: str) -> list[dict]:
    df = df.copy()
    df = _apply_column_aliases(df, table_name)
    df = df.where(pd.notnull(df), None)
    df = df.dropna(how="all")

    schema, required_fields = _TABLE_SCHEMA.get(table_name, ({}, []))

    cleaned = []

    for row in df.to_dict(orient="records"):
        if schema:
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