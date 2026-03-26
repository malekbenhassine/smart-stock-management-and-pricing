import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from ..models.tables import (
    Product, Sale, CompetitorPrice,
    ProductSupplier, Promotion, StockMovement, ImportLog
)


def _parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"true", "1", "yes"}


# ─── fonctions d'import par table ────────────────────────────────────────────

def _import_products(df: pd.DataFrame, db: Session) -> int:
    count = 0
    for _, row in df.iterrows():
        obj = db.get(Product, int(row["product_id"]))
        data = {
            "product_id":    int(row["product_id"]),
            "name":          str(row.get("name", "")),
            "category":      str(row.get("category", "")),
            "current_price": float(row.get("current_price", 0)),
            "cost":          float(row.get("cost", 0)),
            "stock":         int(row.get("stock", 0)),
            "min_price":     float(row.get("min_price", 0)),
            "max_price":     float(row.get("max_price", 0)),
            "weight_kg":     float(row.get("weight_kg", 0)) if pd.notna(row.get("weight_kg")) else None,
            "is_active":     _parse_bool(row.get("is_active", True)),
            "supplier_id":   int(row.get("supplier_id", 0)) if pd.notna(row.get("supplier_id")) else None,
            "lead_time_days":int(row.get("lead_time_days", 7)) if pd.notna(row.get("lead_time_days")) else None,
            "reorder_point": int(row.get("reorder_point", 0)) if pd.notna(row.get("reorder_point")) else None,
            "unit":          str(row.get("unit", "")),
            "tax_rate":      float(row.get("tax_rate", 0)) if pd.notna(row.get("tax_rate")) else None,
        }
        if obj:
            for k, v in data.items():
                setattr(obj, k, v)
        else:
            db.add(Product(**data))
        count += 1
    return count


def _import_sales(df: pd.DataFrame, db: Session) -> int:
    count = 0
    for _, row in df.iterrows():
        obj = db.get(Sale, int(row["sale_id"]))
        data = {
            "sale_id":    int(row["sale_id"]),
            "product_id": int(row["product_id"]),
            "timestamp":  pd.to_datetime(row["timestamp"]),
            "qty":        int(row["qty"]),
            "unit_price": float(row["unit_price"]),
            "channel":    str(row.get("channel", "")),
        }
        if obj:
            for k, v in data.items():
                setattr(obj, k, v)
        else:
            db.add(Sale(**data))
        count += 1
    return count


def _import_competitor_prices(df: pd.DataFrame, db: Session) -> int:
    count = 0
    for _, row in df.iterrows():
        db.add(CompetitorPrice(
            product_id=int(row["product_id"]),
            competitor_id=str(row["competitor_id"]),
            competitor_price=float(row["competitor_price"]),
            collected_at=pd.to_datetime(row["collected_at"]),
            status=str(row.get("status", "OK")),
            source=str(row.get("source", "")),
        ))
        count += 1
    return count


def _import_product_suppliers(df: pd.DataFrame, db: Session) -> int:
    count = 0
    for _, row in df.iterrows():
        db.add(ProductSupplier(
            product_id=int(row["product_id"]),
            supplier_id=int(row["supplier_id"]),
            lead_time_days=int(row.get("lead_time_days", 7)),
            last_cost_price=float(row.get("last_cost_price", 0)) if pd.notna(row.get("last_cost_price")) else None,
            is_preferred=_parse_bool(row.get("is_preferred", False)),
        ))
        count += 1
    return count


def _import_promotions(df: pd.DataFrame, db: Session) -> int:
    count = 0
    for _, row in df.iterrows():
        obj = db.get(Promotion, int(row["promo_id"]))
        data = {
            "promo_id":    int(row["promo_id"]),
            "product_id":  int(row["product_id"]),
            "start_date":  pd.to_datetime(row["start_date"]).date(),
            "end_date":    pd.to_datetime(row["end_date"]).date(),
            "discount_pct":float(row["discount_pct"]),
            "promo_type":  str(row.get("promo_type", "")),
            "channel":     str(row.get("channel", "")),
            "min_qty":     int(row.get("min_qty", 1)) if pd.notna(row.get("min_qty")) else None,
            "max_discount":float(row.get("max_discount", 0)) if pd.notna(row.get("max_discount")) else None,
        }
        if obj:
            for k, v in data.items():
                setattr(obj, k, v)
        else:
            db.add(Promotion(**data))
        count += 1
    return count


def _import_stock_movements(df: pd.DataFrame, db: Session) -> int:
    count = 0
    for _, row in df.iterrows():
        obj = db.get(StockMovement, int(row["movement_id"]))
        data = {
            "movement_id":          int(row["movement_id"]),
            "product_id":           int(row["product_id"]),
            "movement_type":        str(row["movement_type"]),
            "direction":            str(row["direction"]),
            "qty":                  int(row["qty"]),
            "timestamp":            pd.to_datetime(row["timestamp"]),
            "performed_by_user_id": int(row.get("performed_by_user_id", 0)) if pd.notna(row.get("performed_by_user_id")) else None,
            "reference":            str(row.get("reference", "")) if pd.notna(row.get("reference")) else None,
        }
        if obj:
            for k, v in data.items():
                setattr(obj, k, v)
        else:
            db.add(StockMovement(**data))
        count += 1
    return count


# ─── dispatch ────────────────────────────────────────────────────────────────

IMPORTERS = {
    "products":          _import_products,
    "sales":             _import_sales,
    "competitor_prices": _import_competitor_prices,
    "product_suppliers": _import_product_suppliers,
    "promotions":        _import_promotions,
    "stock_movements":   _import_stock_movements,
}


def import_dataframe(df: pd.DataFrame, table_name: str, db: Session) -> int:
    """
    Importe un DataFrame dans la table correspondante.
    Retourne le nombre de lignes importées.
    """
    importer = IMPORTERS.get(table_name)
    if importer is None:
        raise ValueError(f"Pas d'importeur pour la table '{table_name}'")
    return importer(df, db)


def log_import(
    db: Session,
    filename: str,
    table_name: str,
    status: str,
    rows: int = 0,
    error: str = None,
):
    db.add(ImportLog(
        filename=filename,
        table_name=table_name,
        status=status,
        rows_imported=rows,
        error_detail=error,
        imported_at=datetime.utcnow(),
    ))
    db.commit()
