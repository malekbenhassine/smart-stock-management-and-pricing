import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Any
from sklearn.ensemble import GradientBoostingRegressor

from .common_functions import (
    build_weekly_sales,
    competitor_week_median,
    promo_flag_week,
    add_lag_features,
    train_quantile_gbr,
)


@dataclass
class PromoArtifacts:
    m10: GradientBoostingRegressor
    m50: GradientBoostingRegressor
    m90: GradientBoostingRegressor
    feature_cols: List[str]
    meta: Dict[str, Any]


def train_promo_ml(
    products: pd.DataFrame,
    sales: pd.DataFrame,
    competitor_prices: pd.DataFrame,
    promotions: pd.DataFrame,
) -> PromoArtifacts:
    weekly = build_weekly_sales(sales)
    comp = competitor_week_median(competitor_prices)
    promo = promo_flag_week(promotions)

    df = weekly.merge(comp, on=["product_id", "week"], how="left")
    df = df.merge(promo, on=["product_id", "week"], how="left")

    df["comp_median"] = df["comp_median"].fillna(df["price_week"])
    df["promo_flag"] = df["promo_flag"].fillna(0).astype(int)
    df["discount"] = 0.0

    df = add_lag_features(df, target_col="qty_week", lags=4)

    feature_cols = [
        "product_id",
        "price_week",
        "comp_median",
        "promo_flag",
        "discount",
        "lag_1",
        "lag_2",
        "lag_3",
        "lag_4",
        "roll_mean_4",
        "roll_std_4",
        "weekofyear",
    ]

    X = df[feature_cols].values.astype(float)
    y = df["qty_week"].values.astype(float)

    m10 = train_quantile_gbr(X, y, alpha=0.10)
    m50 = train_quantile_gbr(X, y, alpha=0.50)
    m90 = train_quantile_gbr(X, y, alpha=0.90)

    meta = {
        "train_rows": int(len(df)),
        "n_products": int(df["product_id"].nunique()),
    }

    return PromoArtifacts(
        m10=m10,
        m50=m50,
        m90=m90,
        feature_cols=feature_cols,
        meta=meta,
    )