import os
import joblib
import numpy as np

from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from utils import load_and_clean_data, feature_engineering


def train_demand_model(path="train_data.csv"):
    os.makedirs("models", exist_ok=True)

    df = load_and_clean_data(path)
    df = feature_engineering(df, drop_leaky_columns=True)
    df = df.sort_values("date").reset_index(drop=True)

    features = [
        "price", "price_change", "price_lag_1",
        "day", "month", "day_of_week", "week_of_year", "is_weekend", "quarter",
        "is_month_start", "is_month_end", "is_quarter_start", "is_quarter_end",
        "month_sin", "month_cos", "dow_sin", "dow_cos",

        "lag_1", "lag_7", "lag_14", "lag_21", "lag_30", 

        "rolling_mean_7", "rolling_mean_14", "rolling_mean_30", 
        "rolling_std_7", "rolling_max_7", "rolling_min_7",

        "sales_diff", "trend", "trend_short_medium", "trend_medium_long",
        "cumulative_sales"
    ]

    optional_numeric_features = [
        "stock", "stock_lag", "stock_to_sales", "stock_vs_avg_sales",
        "discount", "competitor_pricing", "units_ordered",
        "price_discount_interaction", "price_vs_competitor",
        "competitor_ratio", "promo_discount_interaction"
    ]

    for col in optional_numeric_features:
        if col in df.columns:
            features.append(col)

    encoded_features = [
        col for col in df.columns
        if col.startswith("category_")
        or col.startswith("region_")
        or col.startswith("weather_condition_")
        or col.startswith("holiday_promotion_")
        or col.startswith("seasonality_")
        or col.startswith("store_id_")
        or col.startswith("product_id_")
    ]
    features += encoded_features

    features = [col for col in features if col in df.columns]

    X = df[features].copy()
    y = df["sales"].copy()

    if X.empty:
        raise ValueError("Aucune feature disponible pour l'entraînement.")

    model = XGBRegressor(
        n_estimators=600,
        max_depth=6,
        learning_rate=0.03,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        min_child_weight=3,
        random_state=42,
        objective="reg:squarederror"
    )

    model.fit(X, y)

    train_pred = model.predict(X)
    mae = mean_absolute_error(y, train_pred)
    rmse = float(np.sqrt(mean_squared_error(y, train_pred)))
    r2 = r2_score(y, train_pred)

    joblib.dump(model, "models/demand_model.pkl")
    joblib.dump(features, "models/demand_features.pkl")

    return {
        "status": "training completed",
        "rows_used": len(df),
        "features_used": features,
        "train_results": {
            "MAE": round(mae, 2),
            "RMSE": round(rmse, 2),
            "R2": round(r2, 4)
        }
    }


if __name__ == "__main__":
    result = train_demand_model("train_data.csv")
    print(result)