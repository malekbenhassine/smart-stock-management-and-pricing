import asyncio
import math

import pandas as pd
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from .csv_parser import parse_csv
from .http_clients import post_to_stock, post_to_inference
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
    "concurrents": ("/competitors/bulk", "stock"),
    "produits_concurrents": ("/product-competitors/bulk", "stock"),
    "mouvement_stock": ("/stock-movements/bulk", "stock"),
    "sales_history": ("/sales-history/bulk", "stock"),
}

CHUNK_SIZE_SALES_HISTORY = 1000
ACCEPTED_EXTENSIONS = (".csv", ".json", ".xlsx", ".xls")
_NULL_STRINGS = {"none", "nan", "null", "n/a", "na", "undefined"}


def chunk_list(items: list[dict], chunk_size: int):
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]


def _clean_value(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _safe_int(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        s = str(v).strip()
        return int(float(s)) if s else None
    except Exception:
        return None


def _safe_float(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        s = str(v).strip().replace(",", ".")
        return float(s) if s else None
    except Exception:
        return None


def _safe_str(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    if not s or s.lower() in _NULL_STRINGS:
        return None
    return s


_TABLE_SCHEMA: dict[str, tuple[dict, list[str]]] = {
    "fournisseurs": (
        {"id": "int", "nom": "str", "tel": "str", "adresse": "str", "leadtimejours": "int", "scorefiabilite": "float"},
        ["id", "nom"],
    ),
    "produits": (
        {
            "id": "int", "sku": "str", "nom": "str", "categorie": "str", "marque": "str",
            "description": "str", "prixcout": "float", "prixvente": "float", "margereservee": "float",
            "stockdisponible": "int", "stockreserve": "int", "stockminimum": "int",
            "seuilmax": "int", "seuilmin": "int", "statut": "str",
            "datedebutobservation": "str", "datefinobservation": "str",
        },
        ["id", "sku", "nom"],
    ),
    "commandes_fournisseurs": (
        {
            "id": "int", "fournisseur_id": "int", "idcommande": "str", "datecommande": "str",
            "datereceptionprevue": "str", "datereceptionreelle": "str", "statut": "str",
        },
        ["id", "fournisseur_id", "idcommande"],
    ),
    "lignes_commandes": (
        {
            "id": "int", "commande_id": "int", "produit_id": "int",
            "quantitecommandee": "int", "quantiterecue": "int", "prixachatunitaire": "float",
        },
        ["id", "commande_id", "produit_id"],
    ),
    "ventes": (
        {"id": "int", "datevente": "str", "source": "str", "statut": "str"},
        ["id"],
    ),
    "lignes_ventes": (
        {
            "id": "int", "vente_id": "int", "produit_id": "int",
            "quantite": "int", "prixventeunitaire": "float",
        },
        ["id", "vente_id", "produit_id"],
    ),
    "promotions": (
        {
            "id": "int", "nom": "str", "type": "str", "valeur": "float",
            "datedebut": "str", "datefin": "str", "stockminimumrequis": "int",
            "actif": "str", "prixpromo": "float",
        },
        ["id"],
    ),
    "produit_promotion": (
        {"produit_id": "int", "promotion_id": "int", "prixpromo": "float"},
        ["produit_id", "promotion_id"],
    ),
    "concurrents": (
        {
            "id": "int", "nom": "str", "siteurl": "str", "actif": "str",
            "frequencescrapingheures": "int", "dernierscraping": "str",
        },
        ["id", "nom"],
    ),
    "produits_concurrents": (
        {
            "id": "int", "urlproduit": "str", "skuconcurrent": "str", "nomproduit": "str",
            "concurrent_id": "int", "produit_id": "int", "prixconcurrent": "float",
            "ispromo": "str", "disponibilite": "str", "datecollecte": "str", "fiable": "str",
        },
        ["id", "concurrent_id", "produit_id"],
    ),
    "mouvement_stock": (
        {
            "id": "int", "produit_id": "int", "type": "str",
            "quantite": "int", "datemouvement": "str", "justification": "str",
        },
        ["id", "produit_id", "type"],
    ),
    "sales_history": (
        {
            "date": "str", "store_id": "str", "product_id": "str", "category": "str",
            "region": "str", "units_sold": "float", "price": "float",
            "inventory_level": "float", "discount": "float", "competitor_pricing": "float",
            "units_ordered": "float", "weather_condition": "str",
            "holiday_promotion": "int", "seasonality": "str",
        },
        ["date", "store_id", "product_id"],
    ),
}

_CONVERTERS = {"int": _safe_int, "float": _safe_float, "str": _safe_str}


def clean_records(df: pd.DataFrame, table_name: str) -> list[dict]:
    df = df.copy()
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

        if any(cleaned_row.get(f) is None for f in required_fields):
            continue

        cleaned.append(cleaned_row)

    return cleaned


async def _send_chunks(endpoint: str, target: str, rows: list[dict], chunk_size: int) -> tuple[int, int]:
    chunks = list(chunk_list(rows, chunk_size))
    if not chunks:
        return 0, 0

    post_fn = post_to_stock if target == "stock" else post_to_inference
    results = await asyncio.gather(*[post_fn(endpoint, chunk) for chunk in chunks])

    total_sent = sum(len(chunk) for chunk in chunks)
    return total_sent, len(chunks)


async def process_single_file(file_name: str, content: bytes) -> dict:
    df, table_name = parse_csv(content, file_name)
    rows = clean_records(df, table_name)

    if table_name not in TABLE_TO_ENDPOINT:
        raise ValueError(f"Aucune route cible configurée pour la table '{table_name}'")

    endpoint, target = TABLE_TO_ENDPOINT[table_name]
    chunk_size = CHUNK_SIZE_SALES_HISTORY if table_name == "sales_history" else (len(rows) or 1)

    total_sent, chunk_count = await _send_chunks(endpoint, target, rows, chunk_size)

    return {
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
        },
    }


async def import_single_file(file: UploadFile, db: Session, upsert: bool = False):
    filename = file.filename or ""

    if not any(filename.lower().endswith(ext) for ext in ACCEPTED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté. Formats acceptés : {', '.join(ACCEPTED_EXTENSIONS)}"
        )

    content = await file.read()

    try:
        result = await process_single_file(filename, content)
        log_import_bulk(
            db,
            [{
                "filename": filename,
                "table": result["table"],
                "status": "SUCCESS",
                "rows": result["rows_imported"],
            }]
        )
        return result

    except HTTPException as e:
        log_import_bulk(
            db,
            [{
                "filename": filename,
                "table": "unknown",
                "status": "ERROR",
                "rows": 0,
                "error": str(e.detail),
            }]
        )
        raise
    except Exception as e:
        log_import_bulk(
            db,
            [{
                "filename": filename,
                "table": "unknown",
                "status": "ERROR",
                "rows": 0,
                "error": str(e),
            }]
        )
        raise HTTPException(status_code=500, detail=str(e))


async def import_batch_files(files: list[UploadFile], db: Session, upsert: bool = False):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier envoyé.")

    async def read_file(file: UploadFile) -> tuple[str, bytes | None]:
        filename = file.filename or ""
        if not any(filename.lower().endswith(ext) for ext in ACCEPTED_EXTENSIONS):
            return filename, None
        return filename, await file.read()

    file_contents = await asyncio.gather(*[read_file(f) for f in files])

    async def process(filename: str, content: bytes | None) -> dict:
        if content is None:
            return {
                "status": "error",
                "filename": filename,
                "detail": f"Format non supporté. Formats acceptés : {', '.join(ACCEPTED_EXTENSIONS)}",
            }
        try:
            return await process_single_file(filename, content)
        except HTTPException as e:
            return {"status": "error", "filename": filename, "detail": e.detail}
        except Exception as e:
            return {"status": "error", "filename": filename, "detail": str(e)}

    results = await asyncio.gather(*[process(name, content) for name, content in file_contents])

    log_entries = [
        {
            "filename": r["filename"],
            "table": r.get("table", "unknown"),
            "status": "SUCCESS" if r["status"] == "success" else "ERROR",
            "rows": r.get("rows_imported", 0),
            "error": r.get("detail") if r["status"] != "success" else None,
        }
        for r in results
    ]
    log_import_bulk(db, log_entries)

    success_count = sum(1 for r in results if r["status"] == "success")
    error_count = len(results) - success_count

    return {
        "status": "completed",
        "total_files": len(files),
        "success_count": success_count,
        "error_count": error_count,
        "results": list(results),
    }


def get_import_logs_service(limit: int, db: Session):
    from ..models.tables import ImportLog

    return (
        db.query(ImportLog)
        .order_by(ImportLog.imported_at.desc())
        .limit(limit)
        .all()
    )