from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...services.csv_parser import parse_csv
from ...services.import_service import import_dataframe, log_import
from ...services.ml_trigger import run_ml_on_products

router = APIRouter(prefix="/import", tags=["csv-import"])


@router.post("/csv")
async def import_csv(
    file: UploadFile = File(...),
    run_ml: bool = True,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    Upload un fichier CSV → détection automatique du type →
    validation → sauvegarde PostgreSQL → (optionnel) déclenchement ML.

    Fichiers supportés : products, sales, competitor_prices,
    product_suppliers, promotions, stock_movements.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .csv sont acceptés.")

    # 1. Lecture du fichier
    content = await file.read()

    # 2. Parse + détection du type
    try:
        df, table_name = parse_csv(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 3. Import en base
    try:
        rows = import_dataframe(df, table_name, db)
        db.commit()
        log_import(db, file.filename, table_name, "SUCCESS", rows)
    except Exception as e:
        db.rollback()
        log_import(db, file.filename, table_name, "ERROR", error=str(e))
        raise HTTPException(status_code=500, detail=f"Erreur import BD: {e}")

    # 4. Déclenchement ML en arrière-plan (seulement pour tables pertinentes)
    ml_tables = {"products", "sales", "competitor_prices", "product_suppliers", "promotions"}
    ml_summary = None

    if run_ml and table_name in ml_tables:
        product_ids = df["product_id"].dropna().unique().tolist()
        product_ids = [int(p) for p in product_ids]

        if product_ids:
            background_tasks.add_task(_run_ml_background, product_ids)
            ml_summary = f"ML déclenché en arrière-plan pour {len(product_ids)} produits."

    return {
        "status":      "success",
        "filename":    file.filename,
        "table":       table_name,
        "rows_imported": rows,
        "ml_status":   ml_summary or "non déclenché",
    }


@router.post("/csv/batch")
async def import_csv_batch(
    files: list[UploadFile] = File(...),
    run_ml: bool = True,
    db: Session = Depends(get_db),
):
    """Import de plusieurs CSV en une seule requête."""
    results = []
    all_product_ids = set()

    for file in files:
        if not file.filename.endswith(".csv"):
            results.append({"file": file.filename, "status": "skipped", "reason": "not a csv"})
            continue

        content = await file.read()
        try:
            df, table_name = parse_csv(content, file.filename)
            rows = import_dataframe(df, table_name, db)
            db.commit()
            log_import(db, file.filename, table_name, "SUCCESS", rows)

            if "product_id" in df.columns:
                all_product_ids.update(df["product_id"].dropna().astype(int).tolist())

            results.append({
                "file": file.filename,
                "table": table_name,
                "rows": rows,
                "status": "success",
            })
        except Exception as e:
            db.rollback()
            log_import(db, file.filename, "unknown", "ERROR", error=str(e))
            results.append({"file": file.filename, "status": "error", "detail": str(e)})

    ml_note = None
    if run_ml and all_product_ids:
        ml_note = f"ML à déclencher pour {len(all_product_ids)} produits (appeler /import/ml-run)."

    return {"results": results, "ml_note": ml_note}


@router.get("/logs")
def get_import_logs(limit: int = 50, db: Session = Depends(get_db)):
    """Retourne les derniers logs d'import."""
    from ...models.tables import ImportLog
    from sqlalchemy import desc
    logs = db.query(ImportLog).order_by(desc(ImportLog.imported_at)).limit(limit).all()
    return [
        {
            "id": l.id,
            "filename": l.filename,
            "table": l.table_name,
            "status": l.status,
            "rows": l.rows_imported,
            "error": l.error_detail,
            "at": l.imported_at,
        }
        for l in logs
    ]


def _run_ml_background(product_ids: list[int]):
    """Tâche arrière-plan : appelle le ml_inference_service."""
    run_ml_on_products(product_ids)
