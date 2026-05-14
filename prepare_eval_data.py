"""
prepare_eval_data.py
====================
Prépare les fichiers /data depuis un CSV Kaggle-compatible.

Utilisation :
    python prepare_eval_data.py

Entrée attendue : data/sales.csv avec colonnes Kaggle possibles :
Date, Store ID, Product ID, Category, Region, Inventory Level, Units Sold,
Units Ordered, Demand Forecast, Price, Discount, Weather Condition,
Holiday/Promotion, Competitor Pricing, Seasonality

Sorties créées :
- data/sales.csv normalisé
- data/products.csv
- data/competitor_prices.csv
- data/promotions.csv
- data/product_id_mapping.csv
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
    rename_map = {
        "Date": "date",
        "Store ID": "store_id",
        "Product ID": "product_id",
        "Category": "category",
        "Region": "region",
        "Inventory Level": "stock",
        "Units Sold": "sales",
        "Units Ordered": "units_ordered",
        "Demand Forecast": "demand_forecast",
        "Price": "price",
        "Discount": "discount",
        "Weather Condition": "weather_condition",
        "Holiday/Promotion": "holiday_promotion",
        "Competitor Pricing": "competitor_pricing",
        "Seasonality": "seasonality",
    }
    df = df.copy().rename(columns=rename_map)
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace(" ", "_", regex=False)
        .str.replace("-", "_", regex=False)
        .str.lower()
    )
    return df


def normalize_sales(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    df = normalize_columns(df)
    required = ["date", "product_id", "sales", "price"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes : {missing}. Colonnes disponibles : {list(df.columns)}")

    defaults = {
        "store_id": "S001",
        "category": "UNKNOWN",
        "region": "Tunis",
        "stock": 0,
        "units_ordered": 0,
        "demand_forecast": df["sales"],
        "discount": 0,
        "weather_condition": "Normal",
        "holiday_promotion": 0,
        "competitor_pricing": df["price"],
        "seasonality": "Regular",
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df["timestamp"] = df["date"]

    for col in ["sales", "price", "stock", "units_ordered", "demand_forecast", "discount", "holiday_promotion", "competitor_pricing"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["qty"] = df["sales"].clip(lower=0)
    df["unit_price"] = df["price"].clip(lower=0)
    df["is_promo"] = ((df["discount"] > 0) | (df["holiday_promotion"] > 0)).astype(int)
    df["price_gap_pct"] = (
        (df["price"] - df["competitor_pricing"])
        / df["competitor_pricing"].replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # product_id numérique pour les modèles sklearn ; mapping conservé pour traçabilité
    df["product_id_original"] = df["product_id"].astype(str)
    unique_products = sorted(df["product_id_original"].unique())
    mapping = {pid: i + 1 for i, pid in enumerate(unique_products)}
    df["product_id"] = df["product_id_original"].map(mapping).astype(int)

    return df, mapping


def create_products(df: pd.DataFrame) -> pd.DataFrame:
    products = (
        df.sort_values("timestamp")
        .groupby("product_id", as_index=False)
        .agg(
            sku=("product_id_original", "last"),
            category=("category", "last"),
            current_price=("unit_price", "last"),
            current_stock=("stock", "last"),
            avg_sales=("qty", "mean"),
            competitor_price=("competitor_pricing", "mean"),
        )
    )
    products["name"] = "Produit " + products["sku"].astype(str)
    products["brand"] = products["sku"].astype(str).str.split("-").str[0]
    products["cost_price"] = (products["current_price"] * 0.75).round(2)
    products["margin_rate"] = (
        (products["current_price"] - products["cost_price"])
        / products["current_price"].replace(0, 1)
    ).round(3)
    products["min_stock"] = products["avg_sales"].clip(lower=2).round().astype(int)
    products["reorder_point"] = (products["avg_sales"] * 2).clip(lower=5).round().astype(int)
    products["max_stock"] = (products["avg_sales"] * 8).clip(lower=30).round().astype(int)
    products["lead_time_days"] = 7
    products["status"] = "active"
    return products[
        [
            "product_id", "sku", "name", "category", "brand", "current_price",
            "cost_price", "margin_rate", "current_stock", "min_stock",
            "reorder_point", "max_stock", "lead_time_days", "status", "competitor_price",
        ]
    ]


def create_competitor_prices(df: pd.DataFrame, add_synthetic_competitors: bool = True) -> pd.DataFrame:
    base = df[["timestamp", "product_id", "competitor_pricing", "unit_price"]].copy()
    base = base.rename(columns={"timestamp": "collected_at", "competitor_pricing": "competitor_price"})

    rows = []
    competitors = [
        (1, "Mytek simulé", 1.00),
        (2, "Tunisianet simulé", 1.03),
        (3, "Spacenet simulé", 0.98),
        (4, "Zoom simulé", 1.06),
    ] if add_synthetic_competitors else [(1, "Mytek simulé", 1.00)]

    for competitor_id, competitor_name, factor in competitors:
        part = base.copy()
        part["competitor_id"] = competitor_id
        part["competitor_name"] = competitor_name
        # petite variation déterministe par concurrent
        part["competitor_price"] = (part["competitor_price"] * factor).round(2)
        part["status"] = "OK"
        rows.append(part)

    comp = pd.concat(rows, ignore_index=True)

    # Quelques anomalies contrôlées pour rendre l'évaluation anomalie possible.
    if add_synthetic_competitors and len(comp) > 1000:
        idx_high = comp.sample(frac=0.005, random_state=42).index
        comp.loc[idx_high, "competitor_price"] = (comp.loc[idx_high, "competitor_price"] * 2.2).round(2)
        comp.loc[idx_high, "status"] = "OUTLIER"
        idx_low = comp.drop(index=idx_high).sample(frac=0.005, random_state=43).index
        comp.loc[idx_low, "competitor_price"] = (comp.loc[idx_low, "competitor_price"] * 0.35).round(2)
        comp.loc[idx_low, "status"] = "OUTLIER"

    return comp[["collected_at", "product_id", "competitor_id", "competitor_name", "competitor_price", "status"]]


def create_promotions(df: pd.DataFrame) -> pd.DataFrame:
    promo = df[(df["discount"] > 0) | (df["holiday_promotion"] > 0)].copy()
    cols = ["promotion_id", "product_id", "start_date", "end_date", "discount_percent", "promo_type", "channel", "active", "expected_lift"]
    if promo.empty:
        return pd.DataFrame(columns=cols)
    promo["week_start"] = promo["timestamp"].dt.to_period("W").apply(lambda r: r.start_time)
    promo["week_end"] = promo["week_start"] + pd.Timedelta(days=6)
    grouped = (
        promo.groupby(["product_id", "week_start", "week_end"], as_index=False)
        .agg(discount_percent=("discount", "max"), expected_lift=("qty", "mean"))
    )
    grouped = grouped.reset_index(drop=True)
    grouped["promotion_id"] = grouped.index + 1
    grouped["promo_type"] = "PROMO"
    grouped["channel"] = "online"
    grouped["active"] = True
    grouped = grouped.rename(columns={"week_start": "start_date", "week_end": "end_date"})
    return grouped[cols]


def main():
    if not SALES_PATH.exists():
        raise FileNotFoundError(f"Fichier introuvable : {SALES_PATH}")
    df = pd.read_csv(SALES_PATH)
    sales, mapping = normalize_sales(df)
    products = create_products(sales)
    competitor_prices = create_competitor_prices(sales, add_synthetic_competitors=True)
    promotions = create_promotions(sales)

    sales.to_csv(SALES_PATH, index=False)
    products.to_csv(PRODUCTS_PATH, index=False)
    competitor_prices.to_csv(COMPETITOR_PATH, index=False)
    promotions.to_csv(PROMOTIONS_PATH, index=False)
    pd.DataFrame([{"product_id_original": k, "product_id_numeric": v} for k, v in mapping.items()]).to_csv(MAPPING_PATH, index=False)

    print("✅ Données préparées avec succès")
    print(f"sales.csv              : {len(sales)} lignes | {len(sales.columns)} colonnes")
    print(f"products.csv           : {len(products)} lignes | {len(products.columns)} colonnes")
    print(f"competitor_prices.csv  : {len(competitor_prices)} lignes | {len(competitor_prices.columns)} colonnes")
    print(f"promotions.csv         : {len(promotions)} lignes | {len(promotions.columns)} colonnes")
    print(f"mapping                : {MAPPING_PATH}")


if __name__ == "__main__":
    main()
