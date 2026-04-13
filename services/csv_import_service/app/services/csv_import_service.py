from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session
import pandas as pd
import math

from .csv_parser import parse_csv
from .import_service import log_import
from .http_clients import post_to_stock, post_to_inference


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


def chunk_list(items: list[dict], chunk_size: int):
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]
        
def _clean_value(value):
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _safe_int(v):
    if v is None or pd.isna(v):
        return None
    try:
        s = str(v).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _safe_float(v):
    if v is None or pd.isna(v):
        return None
    try:
        s = str(v).strip().replace(",", ".")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _safe_str(v):
    if v is None or pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


def clean_records(df: pd.DataFrame, table_name: str) -> list[dict]:
    df = df.copy()
    df = df.where(pd.notnull(df), None)
    df = df.dropna(how="all")

    records = df.to_dict(orient="records")
    cleaned = []

    for row in records:
        row = {k: _clean_value(v) for k, v in row.items()}

        if table_name == "fournisseurs":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "nom": _safe_str(row.get("nom")),
                "tel": None if row.get("tel") is None else str(row.get("tel")).strip(),
                "adresse": _safe_str(row.get("adresse")),
                "leadtimejours": _safe_int(row.get("leadtimejours")),
                "scorefiabilite": _safe_float(row.get("scorefiabilite")),
            }
            if cleaned_row["id"] is None or cleaned_row["nom"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "produits":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "sku": _safe_str(row.get("sku")),
                "nom": _safe_str(row.get("nom")),
                "categorie": _safe_str(row.get("categorie")),
                "marque": _safe_str(row.get("marque")),
                "description": _safe_str(row.get("description")),
                "prixcout": _safe_float(row.get("prixcout")),
                "prixvente": _safe_float(row.get("prixvente")),
                "margereservee": _safe_float(row.get("margereservee")),
                "stockdisponible": _safe_int(row.get("stockdisponible")),
                "stockreserve": _safe_int(row.get("stockreserve")),
                "stockminimum": _safe_int(row.get("stockminimum")),
                "seuilmax": _safe_int(row.get("seuilmax")),
                "seuilmin": _safe_int(row.get("seuilmin")),
                "statut": _safe_str(row.get("statut")),
                "datedebutobservation": _safe_str(row.get("datedebutobservation")),
                "datefinobservation": _safe_str(row.get("datefinobservation")),
            }
            if cleaned_row["id"] is None or cleaned_row["sku"] is None or cleaned_row["nom"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "commandes_fournisseurs":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "fournisseur_id": _safe_int(row.get("fournisseur_id")),
                "idcommande": _safe_str(row.get("idcommande")),
                "datecommande": _safe_str(row.get("datecommande")),
                "datereceptionprevue": _safe_str(row.get("datereceptionprevue")),
                "datereceptionreelle": _safe_str(row.get("datereceptionreelle")),
                "statut": _safe_str(row.get("statut")),
            }
            if cleaned_row["id"] is None or cleaned_row["fournisseur_id"] is None or cleaned_row["idcommande"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "lignes_commandes":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "commande_id": _safe_int(row.get("commande_id")),
                "produit_id": _safe_int(row.get("produit_id")),
                "quantitecommandee": _safe_int(row.get("quantitecommandee")),
                "quantiterecue": _safe_int(row.get("quantiterecue")),
                "prixachatunitaire": _safe_float(row.get("prixachatunitaire")),
            }
            if cleaned_row["id"] is None or cleaned_row["commande_id"] is None or cleaned_row["produit_id"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "ventes":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "datevente": _safe_str(row.get("datevente")),
                "source": _safe_str(row.get("source")),
                "statut": _safe_str(row.get("statut")),
            }
            if cleaned_row["id"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "lignes_ventes":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "vente_id": _safe_int(row.get("vente_id")),
                "produit_id": _safe_int(row.get("produit_id")),
                "quantite": _safe_int(row.get("quantite")),
                "prixventeunitaire": _safe_float(row.get("prixventeunitaire")),
            }
            if cleaned_row["id"] is None or cleaned_row["vente_id"] is None or cleaned_row["produit_id"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "promotions":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "nom": _safe_str(row.get("nom")),
                "type": _safe_str(row.get("type")),
                "valeur": _safe_float(row.get("valeur")),
                "datedebut": _safe_str(row.get("datedebut")),
                "datefin": _safe_str(row.get("datefin")),
                "stockminimumrequis": _safe_int(row.get("stockminimumrequis")),
                "actif": _safe_str(row.get("actif")),
                "prixpromo": _safe_float(row.get("prixpromo")),
            }
            if cleaned_row["id"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "produit_promotion":
            cleaned_row = {
                "produit_id": _safe_int(row.get("produit_id")),
                "promotion_id": _safe_int(row.get("promotion_id")),
                "prixpromo": _safe_float(row.get("prixpromo")),
            }
            if cleaned_row["produit_id"] is None or cleaned_row["promotion_id"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "concurrents":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "nom": _safe_str(row.get("nom")),
                "siteurl": _safe_str(row.get("siteurl")),
                "actif": _safe_str(row.get("actif")),
                "frequencescrapingheures": _safe_int(row.get("frequencescrapingheures")),
                "dernierscraping": _safe_str(row.get("dernierscraping")),
            }
            if cleaned_row["id"] is None or cleaned_row["nom"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "produits_concurrents":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "urlproduit": _safe_str(row.get("urlproduit")),
                "skuconcurrent": _safe_str(row.get("skuconcurrent")),
                "nomproduit": _safe_str(row.get("nomproduit")),
                "concurrent_id": _safe_int(row.get("concurrent_id")),
                "produit_id": _safe_int(row.get("produit_id")),
                "prixconcurrent": _safe_float(row.get("prixconcurrent")),
                "ispromo": _safe_str(row.get("ispromo")),
                "disponibilite": _safe_str(row.get("disponibilite")),
                "datecollecte": _safe_str(row.get("datecollecte")),
                "fiable": _safe_str(row.get("fiable")),
            }
            if cleaned_row["id"] is None or cleaned_row["concurrent_id"] is None or cleaned_row["produit_id"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "mouvement_stock":
            cleaned_row = {
                "id": _safe_int(row.get("id")),
                "produit_id": _safe_int(row.get("produit_id")),
                "type": _safe_str(row.get("type")),
                "quantite": _safe_int(row.get("quantite")),
                "datemouvement": _safe_str(row.get("datemouvement")),
                "justification": _safe_str(row.get("justification")),
            }
            if cleaned_row["id"] is None or cleaned_row["produit_id"] is None or cleaned_row["type"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        if table_name == "sales_history":
            cleaned_row = {
                "date": _safe_str(row.get("date")),
                "store_id": _safe_str(row.get("store_id")),
                "product_id": _safe_str(row.get("product_id")),
                "category": _safe_str(row.get("category")),
                "region": _safe_str(row.get("region")),
                "units_sold": _safe_float(row.get("units_sold")),
                "price": _safe_float(row.get("price")),
                "inventory_level": _safe_float(row.get("inventory_level")),
                "discount": _safe_float(row.get("discount")),
                "competitor_pricing": _safe_float(row.get("competitor_pricing")),
                "units_ordered": _safe_float(row.get("units_ordered")),
                "weather_condition": _safe_str(row.get("weather_condition")),
                "holiday_promotion": _safe_int(row.get("holiday_promotion")),
                "seasonality": _safe_str(row.get("seasonality")),
            }
            if cleaned_row["date"] is None or cleaned_row["store_id"] is None or cleaned_row["product_id"] is None:
                continue
            cleaned.append(cleaned_row)
            continue

        cleaned.append(row)

    return cleaned


def process_single_csv(file_name: str, content: bytes, db: Session):
    df, table_name = parse_csv(content, file_name)
    rows = clean_records(df, table_name)

    if table_name not in TABLE_TO_ENDPOINT:
        raise ValueError(f"Aucune route cible configurée pour la table '{table_name}'")

    endpoint, target = TABLE_TO_ENDPOINT[table_name]

    # Cas spécial : gros historique -> envoi par chunks
    if table_name == "sales_history":
        total_sent = 0
        chunk_count = 0

        for chunk in chunk_list(rows, CHUNK_SIZE_SALES_HISTORY):
            if target == "stock":
                result = post_to_stock(endpoint, chunk)
            else:
                result = post_to_inference(endpoint, chunk)

            total_sent += result.get("rows", len(chunk))
            chunk_count += 1

        log_import(db, file_name, table_name, "SUCCESS", total_sent)

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
                "chunk_size": CHUNK_SIZE_SALES_HISTORY,
            },
        }

    if target == "stock":
        result = post_to_stock(endpoint, rows)
    else:
        result = post_to_inference(endpoint, rows)

    log_import(db, file_name, table_name, "SUCCESS", len(rows))

    return {
        "status": "success",
        "filename": file_name,
        "table": table_name,
        "rows_imported": len(rows),
        "target_service": target,
        "target_response": result,
    }


async def import_single_file(file: UploadFile, run_ml: bool, db: Session):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .csv sont acceptés.")

    content = await file.read()

    try:
        result = process_single_csv(file.filename, content, db)
        result["run_ml"] = run_ml
        return result

    except HTTPException as e:
        log_import(db, file.filename, "unknown", "ERROR", error=str(e.detail))
        raise e
    except Exception as e:
        log_import(db, file.filename, "unknown", "ERROR", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def import_batch_files(files: list[UploadFile], run_ml: bool, db: Session):
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier envoyé.")

    results = []
    success_count = 0
    error_count = 0

    for file in files:
        if not file.filename.endswith(".csv"):
            results.append({
                "status": "error",
                "filename": file.filename,
                "detail": "Seuls les fichiers .csv sont acceptés."
            })
            error_count += 1
            continue

        try:
            content = await file.read()
            result = process_single_csv(file.filename, content, db)
            results.append(result)
            success_count += 1

        except HTTPException as e:
            log_import(db, file.filename, "unknown", "ERROR", error=str(e.detail))
            results.append({
                "status": "error",
                "filename": file.filename,
                "detail": e.detail,
            })
            error_count += 1

        except Exception as e:
            log_import(db, file.filename, "unknown", "ERROR", error=str(e))
            results.append({
                "status": "error",
                "filename": file.filename,
                "detail": str(e),
            })
            error_count += 1

    return {
        "status": "completed",
        "run_ml": run_ml,
        "total_files": len(files),
        "success_count": success_count,
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