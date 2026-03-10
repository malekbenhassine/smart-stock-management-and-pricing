import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Any
from sklearn.ensemble import GradientBoostingRegressor

@dataclass
class PromoArtifacts:
    m10: GradientBoostingRegressor
    m50: GradientBoostingRegressor
    m90: GradientBoostingRegressor
    feature_cols: List[str]
    meta: Dict[str, Any]

def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    df = sales.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time
    w = df.groupby(["product_id","week"], as_index=False).agg(
        qty_week=("qty","sum"),
        price_week=("unit_price","mean"),
    )
    return w.sort_values(["product_id","week"])

def competitor_week_median(competitor_prices: pd.DataFrame) -> pd.DataFrame:
    df = competitor_prices.copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    df["week"] = df["collected_at"].dt.to_period("W").dt.start_time
    med = df.groupby(["product_id","week"], as_index=False)["competitor_price"].median()
    return med.rename(columns={"competitor_price":"comp_median"})

def promo_flag_week(promotions: pd.DataFrame) -> pd.DataFrame:
    df = promotions.copy()
    if df.empty:
        return pd.DataFrame(columns=["product_id","week","promo_flag"])
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])

    rows = []
    for r in df.itertuples(index=False):
        pid = int(r.product_id)
        start = pd.to_datetime(r.start_date).to_period("W").start_time
        end = pd.to_datetime(r.end_date).to_period("W").start_time
        weeks = pd.date_range(start, end, freq="W-MON")
        for w in weeks:
            rows.append((pid, pd.to_datetime(w), 1))
    return pd.DataFrame(rows, columns=["product_id","week","promo_flag"]).drop_duplicates()

def _train_quantile_gbr(X: np.ndarray, y: np.ndarray, alpha: float) -> GradientBoostingRegressor:
    m = GradientBoostingRegressor(
        loss="quantile",
        alpha=alpha,
        n_estimators=400,
        learning_rate=0.05,
        max_depth=3,
        random_state=42,
    )
    m.fit(X, y)
    return m

def train_promo_ml(products: pd.DataFrame, sales: pd.DataFrame,
                   competitor_prices: pd.DataFrame, promotions: pd.DataFrame) -> PromoArtifacts:
    weekly = build_weekly_sales(sales)
    comp = competitor_week_median(competitor_prices)
    promo = promo_flag_week(promotions)

    df = weekly.merge(comp, on=["product_id","week"], how="left")
    df = df.merge(promo, on=["product_id","week"], how="left")

    df["comp_median"] = df["comp_median"].fillna(df["price_week"])
    df["promo_flag"] = df["promo_flag"].fillna(0).astype(int)

    df = df.sort_values(["product_id","week"])
    for i in range(1, 5):
        df[f"lag_{i}"] = df.groupby("product_id")["qty_week"].shift(i)
    df = df.dropna(subset=[f"lag_{i}" for i in range(1,5)]).copy()

    df["roll_mean_4"] = df[[f"lag_{i}" for i in range(1,5)]].mean(axis=1)
    df["roll_std_4"] = df[[f"lag_{i}" for i in range(1,5)]].std(axis=1).fillna(0.0)
    df["weekofyear"] = pd.to_datetime(df["week"]).dt.isocalendar().week.astype(int)

    # discount sera simulé côté inference, donc en training on le met 0
    df["discount"] = 0.0

    feature_cols = [
        "product_id",
        "price_week",
        "comp_median",
        "promo_flag",
        "discount",
        "lag_1","lag_2","lag_3","lag_4",
        "roll_mean_4","roll_std_4",
        "weekofyear",
    ]

    X = df[feature_cols].values.astype(float)
    y = df["qty_week"].values.astype(float)

    m10 = _train_quantile_gbr(X, y, 0.10)
    m50 = _train_quantile_gbr(X, y, 0.50)
    m90 = _train_quantile_gbr(X, y, 0.90)

    meta = {"train_rows": int(len(df)), "n_products": int(df["product_id"].nunique())}
    return PromoArtifacts(m10, m50, m90, feature_cols, meta)