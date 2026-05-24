from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...services.alert_event_client import emit_alert_event
from ...services.csv_import_service import (
    get_import_logs_service,
    import_batch_files,
    import_single_file,
)

router = APIRouter(prefix="/import", tags=["csv-import"])


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
    "ventes": ["ventes", "vente", "sales", "sale"],
    "lignes_ventes": [
        "lignes_ventes",
        "ligne_vente",
        "sale_lines",
        "sales_lines",
        "details_ventes",
    ],
    "promotions": ["promotions", "promotion", "promos", "promo"],
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


def _normalize_name(value: Any) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = text.lower()
    text = text.replace(" ", "_").replace("/", "_").replace("-", "_").replace(".", "_")
    text = re.sub(r"[^a-z0-9_]+", "", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _filename_without_extension(filename: str | None) -> str:
    base = os.path.basename(str(filename or ""))
    base = base.split("/")[-1].split("\\")[-1]

    if "." in base:
        base = base.rsplit(".", 1)[0]

    return _normalize_name(base)


def _detect_table_from_filename(filename: str | None) -> str:
    name = _filename_without_extension(filename)

    if not name:
        return "données"

    for table_name in TABLE_DETECTION_ORDER:
        aliases = TABLE_FILE_ALIASES.get(table_name, [])

        for alias in aliases:
            alias = _normalize_name(alias)

            if (
                name == alias
                or name.startswith(alias + "_")
                or name.endswith("_" + alias)
                or f"_{alias}_" in name
            ):
                return table_name

    return "données"


def _extract_rows_count(result: Any) -> int:
    if not isinstance(result, dict):
        return 0

    for key in (
        "rows_imported",
        "imported_rows",
        "inserted",
        "inserted_rows",
        "new_rows",
        "created",
        "created_rows",
        "total_inserted",
        "total_rows",
        "rows",
        "processed_rows",
        "analyzed_rows",
        "lignes_importees",
        "lignesImportees",
        "lignes_analysees",
    ):
        value = result.get(key)

        if isinstance(value, int):
            return value

        if isinstance(value, str) and value.isdigit():
            return int(value)

    if isinstance(result.get("summary"), dict):
        return _extract_rows_count(result["summary"])

    if isinstance(result.get("data"), dict):
        return _extract_rows_count(result["data"])

    return 0


def _extract_table_name(result: Any, filename: str | None = None) -> str:
    if isinstance(result, dict):
        table = (
            result.get("table")
            or result.get("type")
            or result.get("entity")
            or result.get("import_type")
        )

        if table:
            return str(table)

    return _detect_table_from_filename(filename)


def _emit_csv_success_alert(
    *,
    user_id: int | None,
    filename: str,
    rows_count: int,
    upsert: bool,
    table: str = "données",
):
    metadata = {
        "filename": filename,
        "table": table,
        "rows_imported": rows_count,
        "rows_count": rows_count,
        "upsert": upsert,
        "message": f"Votre import de {table} est terminé : {rows_count} ligne(s).",
    }

    emit_alert_event(
        event_type="CSV_IMPORT_SUCCESS",
        source_service="csv_import_service",
        user_id=user_id,
        value=rows_count,
        metadata=metadata,
    )


def _emit_csv_failed_alert(
    *,
    user_id: int | None,
    filename: str,
    error: str,
    upsert: bool,
    table: str = "données",
):
    """
    Important :
    - Le message visible est généré proprement par alerts_service.
    - On envoie quand même l'erreur technique dans metadata.technical_error
      pour permettre à alerts_service de détecter le champ réellement bloquant.
    """
    metadata = {
        "filename": filename,
        "table": table,
        "technical_error": error,
        "error": error,
        "upsert": upsert,
        "message": f"Votre import de {table} a échoué.",
    }

    emit_alert_event(
        event_type="CSV_IMPORT_FAILED",
        source_service="csv_import_service",
        user_id=user_id,
        metadata=metadata,
    )


@router.post("/csv")
async def import_csv(
    file: UploadFile = File(...),
    upsert: bool = Query(default=False),
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    filename = file.filename or "fichier importé"
    guessed_table = _detect_table_from_filename(filename)

    try:
        result = await import_single_file(file=file, db=db, upsert=upsert)

        rows_count = _extract_rows_count(result)
        table = _extract_table_name(result, filename=filename)

        _emit_csv_success_alert(
            user_id=user_id,
            filename=filename,
            rows_count=rows_count,
            upsert=upsert,
            table=table,
        )

        return result

    except Exception as exc:
        _emit_csv_failed_alert(
            user_id=user_id,
            filename=filename,
            table=guessed_table,
            error=str(exc),
            upsert=upsert,
        )
        raise


@router.post("/csv/batch")
async def import_csv_batch(
    files: list[UploadFile] = File(...),
    upsert: bool = Query(default=False),
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    filenames = [file.filename or "fichier importé" for file in files]
    filenames_text = ", ".join(filenames)

    try:
        result = await import_batch_files(files=files, db=db, upsert=upsert)
        results = result.get("results", []) if isinstance(result, dict) else []

        total_rows = sum(
            _extract_rows_count(item)
            for item in results
            if isinstance(item, dict)
        )

        _emit_csv_success_alert(
            user_id=user_id,
            filename=filenames_text,
            table="batch",
            rows_count=total_rows,
            upsert=upsert,
        )

        return result

    except Exception as exc:
        guessed_tables = sorted(
            {
                _detect_table_from_filename(filename)
                for filename in filenames
                if filename
            }
        )

        table = guessed_tables[0] if len(guessed_tables) == 1 else "batch"

        _emit_csv_failed_alert(
            user_id=user_id,
            filename=filenames_text,
            table=table,
            error=str(exc),
            upsert=upsert,
        )
        raise


@router.get("/logs")
def get_import_logs(
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return get_import_logs_service(limit=limit, db=db)
