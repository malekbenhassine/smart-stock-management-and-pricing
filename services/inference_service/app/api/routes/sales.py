# inference_service / routes/sales.py
"""
Route d'ingestion des données de ventes historiques.
Permet d'alimenter la table sales_history depuis :
  - Un enregistrement unique (POST /sales/record)
  - Un fichier CSV complet  (POST /sales/upload-csv)
"""

import io
import pandas as pd
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db, SalesHistory
from app.schemas import SalesRecord, SalesIngestionResponse

router = APIRouter(prefix="/sales")


def _upsert_record(db: Session, rec: SalesRecord) -> bool:
    """Insère ou met à jour un enregistrement (store × product × date)."""
    existing = (
        db.query(SalesHistory)
        .filter(
            SalesHistory.store_id   == rec.store_id,
            SalesHistory.product_id == rec.product_id,
            SalesHistory.date       == rec.date,
        )
        .first()
    )
    if existing:
        existing.sales              = rec.sales
        existing.price              = rec.price
        existing.stock              = rec.stock
        existing.discount           = rec.discount
        existing.competitor_pricing = rec.competitor_pricing
        existing.units_ordered      = rec.units_ordered
        existing.weather_condition  = rec.weather_condition
        existing.holiday_promotion  = rec.holiday_promotion
        existing.seasonality        = rec.seasonality
        existing.category           = rec.category
        existing.region             = rec.region
        return False  # update
    else:
        db.add(SalesHistory(
            date               = rec.date,
            store_id           = rec.store_id,
            product_id         = rec.product_id,
            category           = rec.category,
            region             = rec.region,
            sales              = rec.sales,
            price              = rec.price,
            stock              = rec.stock,
            discount           = rec.discount,
            competitor_pricing = rec.competitor_pricing,
            units_ordered      = rec.units_ordered,
            weather_condition  = rec.weather_condition,
            holiday_promotion  = rec.holiday_promotion,
            seasonality        = rec.seasonality,
        ))
        return True  # insert


@router.post("/record", response_model=SalesIngestionResponse)
def ingest_record(rec: SalesRecord, db: Session = Depends(get_db)):
    """Insère un seul enregistrement de vente."""
    inserted = _upsert_record(db, rec)
    db.commit()
    return SalesIngestionResponse(
        inserted=1 if inserted else 0,
        message="Enregistrement inséré." if inserted else "Enregistrement mis à jour.",
    )


@router.post("/records", response_model=SalesIngestionResponse)
def ingest_records(records: List[SalesRecord], db: Session = Depends(get_db)):
    """Insère une liste d'enregistrements de ventes (batch JSON)."""
    n_inserted = 0
    for rec in records:
        if _upsert_record(db, rec):
            n_inserted += 1
    db.commit()
    return SalesIngestionResponse(
        inserted=n_inserted,
        message=f"{n_inserted} insérés, {len(records)-n_inserted} mis à jour.",
    )


@router.post("/upload-csv", response_model=SalesIngestionResponse)
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Importe un CSV d'historique de ventes.
    Colonnes attendues (noms flexibles, voir mapping ci-dessous) :
      Date, Store ID, Product ID, Category, Region,
      Inventory Level, Units Sold, Units Ordered, Price,
      Discount, Weather Condition, Holiday/Promotion,
      Competitor Pricing, Seasonality
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .csv sont acceptés.")

    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le CSV : {e}")

    # Normalisation des colonnes
    df.columns = (
        df.columns.str.strip().str.lower()
        .str.replace(" ", "_").str.replace("/", "_").str.replace("-", "_")
    )
    col_map = {
        "date":               ["date", "datetime"],
        "store_id":           ["store_id", "store"],
        "product_id":         ["product_id", "product"],
        "category":           ["category", "categorie"],
        "region":             ["region", "zone"],
        "sales":              ["units_sold", "sales", "quantity"],
        "price":              ["price", "unit_price"],
        "stock":              ["inventory_level", "stock"],
        "discount":           ["discount", "remise"],
        "competitor_pricing": ["competitor_pricing"],
        "units_ordered":      ["units_ordered"],
        "weather_condition":  ["weather_condition", "weather"],
        "holiday_promotion":  ["holiday_promotion"],
        "seasonality":        ["seasonality", "season"],
    }
    rename = {}
    for standard, candidates in col_map.items():
        for c in candidates:
            if c in df.columns and standard not in df.columns:
                rename[c] = standard
    df = df.rename(columns=rename)

    required = ["date", "store_id", "product_id", "sales", "price"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes dans le CSV : {missing}"
        )

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "sales", "price"])

    n_inserted = 0
    for _, row in df.iterrows():
        rec = SalesRecord(
            date               = row["date"].date(),
            store_id           = str(row["store_id"]),
            product_id         = str(row["product_id"]),
            category           = row.get("category"),
            region             = row.get("region"),
            sales              = float(row["sales"]),
            price              = float(row["price"]),
            stock              = float(row["stock"])              if "stock"              in row and pd.notna(row["stock"])              else None,
            discount           = float(row["discount"])           if "discount"           in row and pd.notna(row["discount"])           else 0.0,
            competitor_pricing = float(row["competitor_pricing"]) if "competitor_pricing" in row and pd.notna(row["competitor_pricing"]) else None,
            units_ordered      = float(row["units_ordered"])      if "units_ordered"      in row and pd.notna(row["units_ordered"])      else 0.0,
            weather_condition  = row.get("weather_condition"),
            holiday_promotion  = int(row["holiday_promotion"])    if "holiday_promotion"  in row and pd.notna(row["holiday_promotion"])  else 0,
            seasonality        = row.get("seasonality"),
        )
        if _upsert_record(db, rec):
            n_inserted += 1

    db.commit()
    return SalesIngestionResponse(
        inserted=n_inserted,
        message=f"CSV traité : {n_inserted} insérés, {len(df)-n_inserted} mis à jour.",
    )


@router.get("/history")
def get_history(
    store_id:   str,
    product_id: str,
    limit:      int = 30,
    db: Session = Depends(get_db),
):
    """Retourne les derniers enregistrements pour un store × product."""
    rows = (
        db.query(SalesHistory)
        .filter(
            SalesHistory.store_id   == store_id,
            SalesHistory.product_id == product_id,
        )
        .order_by(SalesHistory.date.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "date":    r.date,
            "sales":   r.sales,
            "price":   r.price,
            "stock":   r.stock,
            "discount": r.discount,
        }
        for r in rows
    ]
