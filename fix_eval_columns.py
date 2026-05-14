"""
fix_eval_columns.py
===================
Corrige les colonnes des fichiers data/*.csv sans recréer complètement le dataset.
À lancer si evaluate_models.py se plaint de colonnes manquantes.

Ordre recommandé :
    python prepare_eval_data.py     # si tu pars du CSV Kaggle brut
    python evaluate_models.py

Ou seulement :
    python fix_eval_columns.py
    python evaluate_models.py
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SALES_PATH = DATA_DIR / "sales.csv"
PRODUCTS_PATH = DATA_DIR / "products.csv"
COMPETITOR_PATH = DATA_DIR / "competitor_prices.csv"
PROMOTIONS_PATH = DATA_DIR / "promotions.csv"
MAPPING_PATH = DATA_DIR / "product_id_mapping.csv"


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.astype(str).str.strip().str.replace(" ", "_").str.replace("-", "_").str.lower()
    return df


def main():
    sales = normalize_columns(pd.read_csv(SALES_PATH))

    aliases = {
        "date": "timestamp",
        "sales": "qty",
        "units_sold": "qty",
        "price": "unit_price",
        "competitor_price": "competitor_pricing",
        "inventory_level": "stock",
    }
    for src, dst in aliases.items():
        if src in sales.columns and dst not in sales.columns:
            sales[dst] = sales[src]

    if "timestamp" not in sales.columns:
        raise ValueError("sales.csv doit contenir timestamp ou date")
    if "product_id" not in sales.columns:
        raise ValueError("sales.csv doit contenir product_id")
    if "qty" not in sales.columns:
        raise ValueError("sales.csv doit contenir qty, sales ou units_sold")
    if "unit_price" not in sales.columns:
        raise ValueError("sales.csv doit contenir unit_price ou price")

    sales["timestamp"] = pd.to_datetime(sales["timestamp"], errors="coerce")
    sales = sales.dropna(subset=["timestamp"]).copy()

    defaults = {"stock": 0, "discount": 0, "holiday_promotion": 0, "competitor_pricing": sales["unit_price"]}
    for col, default in defaults.items():
        if col not in sales.columns:
            sales[col] = default

    for col in ["qty", "unit_price", "stock", "discount", "holiday_promotion", "competitor_pricing"]:
        sales[col] = pd.to_numeric(sales[col], errors="coerce").fillna(0)

    sales["product_id_original"] = sales["product_id"].astype(str)
    unique_products = sorted(sales["product_id_original"].unique())
    mapping = {pid: i + 1 for i, pid in enumerate(unique_products)}
    # Si product_id est déjà numérique cohérent, le remapping ne casse pas les modèles sklearn
    sales["product_id"] = sales["product_id_original"].map(mapping).astype(int)
    sales["is_promo"] = ((sales["discount"] > 0) | (sales["holiday_promotion"] > 0)).astype(int)
    sales["price_gap_pct"] = ((sales["unit_price"] - sales["competitor_pricing"]) / sales["competitor_pricing"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0)
    sales.to_csv(SALES_PATH, index=False)
    pd.DataFrame([{"product_id_original": k, "product_id_numeric": v} for k, v in mapping.items()]).to_csv(MAPPING_PATH, index=False)

    # products.csv
    if PRODUCTS_PATH.exists():
        products = normalize_columns(pd.read_csv(PRODUCTS_PATH))
    else:
        products = pd.DataFrame()

    if products.empty:
        products = sales.groupby("product_id", as_index=False).agg(
            current_price=("unit_price", "last"),
            current_stock=("stock", "last"),
            category=("category", "last") if "category" in sales.columns else ("product_id_original", "last"),
        )
    else:
        if "current_price" not in products.columns:
            products["current_price"] = products["price"] if "price" in products.columns else products.get("competitor_price", 0)
        if "current_stock" not in products.columns:
            products["current_stock"] = products["stock"] if "stock" in products.columns else 0
        if "product_id_original" not in products.columns:
            products["product_id_original"] = products["product_id"].astype(str)
        products["product_id"] = products["product_id_original"].map(mapping).fillna(pd.to_numeric(products["product_id_original"], errors="coerce")).fillna(0).astype(int)
    if "status" not in products.columns:
        products["status"] = "active"
    products.to_csv(PRODUCTS_PATH, index=False)

    # competitor_prices.csv
    if COMPETITOR_PATH.exists():
        comp = normalize_columns(pd.read_csv(COMPETITOR_PATH))
        if "collected_at" not in comp.columns:
            comp["collected_at"] = comp["timestamp"] if "timestamp" in comp.columns else comp.get("date", sales["timestamp"].min())
        if "competitor_price" not in comp.columns:
            comp["competitor_price"] = comp["competitor_pricing"] if "competitor_pricing" in comp.columns else comp.get("price", comp.get("unit_price", 0))
        if "competitor_id" not in comp.columns:
            comp["competitor_id"] = 1
        if "competitor_name" not in comp.columns:
            comp["competitor_name"] = "Concurrent simulé"
        if "status" not in comp.columns:
            comp["status"] = "OK"
        comp["product_id_original"] = comp["product_id"].astype(str)
        comp["product_id"] = comp["product_id_original"].map(mapping).fillna(pd.to_numeric(comp["product_id_original"], errors="coerce")).fillna(0).astype(int)
        comp = comp[["collected_at", "product_id", "competitor_id", "competitor_name", "competitor_price", "status"]]
        comp.to_csv(COMPETITOR_PATH, index=False)

    print("✅ Correction terminée")
    print("sales.csv colonnes :", list(pd.read_csv(SALES_PATH, nrows=1).columns))
    print("products.csv colonnes :", list(pd.read_csv(PRODUCTS_PATH, nrows=1).columns))
    if COMPETITOR_PATH.exists():
        print("competitor_prices.csv colonnes :", list(pd.read_csv(COMPETITOR_PATH, nrows=1).columns))
    print(f"Mapping produit créé : {MAPPING_PATH}")


if __name__ == "__main__":
    main()
