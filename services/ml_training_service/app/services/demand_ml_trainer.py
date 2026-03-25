import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any
from sklearn.ensemble import GradientBoostingRegressor

from .common_functions import train_quantile_gbr


@dataclass
class DemandMLArtifacts:
    model_p10: GradientBoostingRegressor
    model_p50: GradientBoostingRegressor
    model_p90: GradientBoostingRegressor
    feature_cols: List[str]
    meta: Dict[str, Any]


def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    df = sales.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time

    weekly = df.groupby(["product_id", "week"], as_index=False).agg(
        qty=("qty", "sum"),
        price_week=("unit_price", "mean"),
    )

    return weekly.sort_values(["product_id", "week"])


def make_supervised_features(weekly: pd.DataFrame, lags: int = 4) -> Tuple[pd.DataFrame, List[str]]:
    df = weekly.copy()
    df["product_id"] = df["product_id"].astype(int)
    df = df.sort_values(["product_id", "week"])

    for i in range(1, lags + 1):
        df[f"lag_{i}"] = df.groupby("product_id")["qty"].shift(i)

    lag_cols = [f"lag_{i}" for i in range(1, lags + 1)]
    df = df.dropna(subset=lag_cols).copy()

    df["roll_mean_4"] = df[lag_cols].mean(axis=1)
    df["roll_std_4"] = df[lag_cols].std(axis=1).fillna(0.0)
    df["weekofyear"] = pd.to_datetime(df["week"]).dt.isocalendar().week.astype(int)

    feature_cols = [
        "product_id",
        "price_week",
        "weekofyear",
        "lag_1",
        "lag_2",
        "lag_3",
        "lag_4",
        "roll_mean_4",
        "roll_std_4",
    ]

    return df, feature_cols


def train_demand_ml(sales: pd.DataFrame) -> DemandMLArtifacts:
    weekly = build_weekly_sales(sales)
    supervised, feature_cols = make_supervised_features(weekly, lags=4)

    X = supervised[feature_cols].values.astype(float)
    y = supervised["qty"].values.astype(float)

    model_p10 = train_quantile_gbr(X, y, alpha=0.10, n_estimators=300)
    model_p50 = train_quantile_gbr(X, y, alpha=0.50, n_estimators=300)
    model_p90 = train_quantile_gbr(X, y, alpha=0.90, n_estimators=300)

    meta = {
        "train_rows": int(len(supervised)),
        "n_products": int(supervised["product_id"].nunique()),
        "lags": 4,
    }

    return DemandMLArtifacts(
        model_p10=model_p10,
        model_p50=model_p50,
        model_p90=model_p90,
        feature_cols=feature_cols,
        meta=meta,
    )


def build_features_for_product_next_week(
    weekly: pd.DataFrame,
    product_id: int,
    feature_cols: List[str]
) -> Dict[str, float]:
    product_data = weekly[weekly["product_id"] == product_id].sort_values("week")
    qty_values = product_data["qty"].values.astype(float)

    if len(qty_values) < 4:
        return {}

    lag_1 = qty_values[-1]
    lag_2 = qty_values[-2]
    lag_3 = qty_values[-3]
    lag_4 = qty_values[-4]

    last_week = pd.to_datetime(product_data["week"].iloc[-1])
    next_week = last_week + pd.Timedelta(days=7)
    weekofyear = int(next_week.isocalendar().week)

    price_week = float(product_data["price_week"].iloc[-1])

    features = {
        "product_id": float(product_id),
        "price_week": price_week,
        "weekofyear": float(weekofyear),
        "lag_1": float(lag_1),
        "lag_2": float(lag_2),
        "lag_3": float(lag_3),
        "lag_4": float(lag_4),
        "roll_mean_4": float(np.mean([lag_1, lag_2, lag_3, lag_4])),
        "roll_std_4": float(np.std([lag_1, lag_2, lag_3, lag_4])),
    }

    return {col: features[col] for col in feature_cols}