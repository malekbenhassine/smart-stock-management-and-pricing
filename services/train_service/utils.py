import pandas as pd
import numpy as np


def standardize_columns(df):
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace("-", "_")
    )

    column_mapping = {
        "date": ["date", "datetime", "day", "jour", "fecha", "timestamp"],
        "sales": ["sales", "sale", "demand", "quantity", "qty", "ventes", "vente", "demandes", "units_sold"],
        "price": ["price", "prix", "unit_price", "selling_price", "montant", "cost"],
        "stock": ["stock", "inventory", "inventaire", "available_stock", "qte_stock", "inventory_level"],
        "store_id": ["store_id", "store", "shop_id", "magasin_id"],
        "product_id": ["product_id", "product", "item_id", "produit_id"],
        "category": ["category", "categorie", "product_category"],
        "region": ["region", "zone", "area"],
        "units_ordered": ["units_ordered", "ordered_units", "quantity_ordered", "orders"],
        "demand_forecast": ["demand_forecast", "forecast", "sales_forecast", "prevision_demande"],
        "discount": ["discount", "remise", "promo_discount"],
        "weather_condition": ["weather_condition", "weather", "meteo", "climate"],
        "holiday_promotion": ["holiday/promotion", "holiday_promotion", "promotion", "holiday", "is_holiday"],
        "competitor_pricing": ["competitor_pricing", "competitor_price", "prix_concurrent"],
        "seasonality": ["seasonality", "season", "saison"]
    }

    rename_dict = {}

    for standard_name, possible_names in column_mapping.items():
        for col in df.columns:
            if col in possible_names:
                rename_dict[col] = standard_name
                break

    df = df.rename(columns=rename_dict)
    return df


def load_and_clean_data(path):
    df = pd.read_csv(path)
    df = standardize_columns(df)

    required_columns = ["date", "sales", "price"]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        raise ValueError(
            f"Colonnes obligatoires manquantes après mapping : {missing_columns}. "
            f"Colonnes trouvées : {list(df.columns)}"
        )

    df = df.drop_duplicates().copy()

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()

    numeric_cols = [
        "sales", "price", "stock", "units_ordered",
        "discount", "competitor_pricing", "demand_forecast"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["sales", "price"]).copy()
    return df


def feature_engineering(df, drop_leaky_columns=True):
    df = df.copy()

    if drop_leaky_columns and "demand_forecast" in df.columns:
        df = df.drop(columns=["demand_forecast"])

    group_cols = []
    if "store_id" in df.columns:
        group_cols.append("store_id")
    if "product_id" in df.columns:
        group_cols.append("product_id")

    sort_cols = group_cols + ["date"] if group_cols else ["date"]
    df = df.sort_values(sort_cols).reset_index(drop=True)

    # =========================
    # FEATURES TEMPORELLES
    # =========================
    df["day"] = df["date"].dt.day
    df["month"] = df["date"].dt.month
    df["day_of_week"] = df["date"].dt.weekday
    df["week_of_year"] = df["date"].dt.isocalendar().week.astype(int)
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    df["quarter"] = df["date"].dt.quarter

    df["is_month_start"] = df["date"].dt.is_month_start.astype(int)
    df["is_month_end"] = df["date"].dt.is_month_end.astype(int)
    df["is_quarter_start"] = df["date"].dt.is_quarter_start.astype(int)
    df["is_quarter_end"] = df["date"].dt.is_quarter_end.astype(int)

    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

    # =========================
    # FEATURES HISTORIQUES
    # =========================
    if group_cols:
        g = df.groupby(group_cols, group_keys=False)

        df["lag_1"] = g["sales"].shift(1)
        df["lag_7"] = g["sales"].shift(7)
        df["lag_14"] = g["sales"].shift(14)
        df["lag_21"] = g["sales"].shift(21)
        df["lag_30"] = g["sales"].shift(30)

        df["price_lag_1"] = g["price"].shift(1)

        if "stock" in df.columns:
            df["stock_lag"] = g["stock"].shift(1)

        df["price_change"] = g["price"].pct_change()

        df["rolling_mean_7"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(7, min_periods=7).mean()
        )
        df["rolling_mean_14"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(14, min_periods=14).mean()
        )
        df["rolling_mean_30"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(30, min_periods=30).mean()
    )

        df["rolling_std_7"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(7, min_periods=7).std()
        )
        df["rolling_max_7"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(7, min_periods=7).max()
        )
        df["rolling_min_7"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(7, min_periods=7).min()
        )

        df["sales_diff"] = g["sales"].transform(lambda s: s.shift(1).diff())
        df["cumulative_sales"] = g["sales"].transform(lambda s: s.shift(1).cumsum())

    else:
        df["lag_1"] = g["sales"].shift(1)
        df["lag_7"] = g["sales"].shift(7)
        df["lag_14"] = g["sales"].shift(14)
        df["lag_21"] = g["sales"].shift(21)
        df["lag_30"] = g["sales"].shift(30)

        df["rolling_mean_7"] = df["sales"].shift(1).rolling(7, min_periods=7).mean()
        df["rolling_mean_14"] = df["sales"].shift(1).rolling(14, min_periods=14).mean()
        df["rolling_mean_30"] = df["sales"].shift(1).rolling(30, min_periods=30).mean()

        df["rolling_std_7"] = df["sales"].shift(1).rolling(7, min_periods=7).std()
        df["rolling_max_7"] = df["sales"].shift(1).rolling(7, min_periods=7).max()
        df["rolling_min_7"] = df["sales"].shift(1).rolling(7, min_periods=7).min()

        df["sales_diff"] = df["sales"].shift(1).diff()
        df["cumulative_sales"] = df["sales"].shift(1).cumsum()

        df["price_change"] = df["price"].pct_change()
        df["price_lag_1"] = df["price"].shift(1)

        if "stock" in df.columns:
            df["stock_lag"] = df["stock"].shift(1)

    # =========================
    # FEATURES DÉRIVÉES
    # =========================
    df["trend"] = df["rolling_mean_7"] - df["rolling_mean_30"]
    df["trend_short_medium"] = df["rolling_mean_7"] - df["rolling_mean_14"]
    df["trend_medium_long"] = df["rolling_mean_14"] - df["rolling_mean_30"]

    if "stock" in df.columns:
        df["stock_to_sales"] = df["stock_lag"] / (df["lag_1"] + 1)
        df["stock_vs_avg_sales"] = df["stock_lag"] / (df["rolling_mean_7"] + 1)

    if "discount" in df.columns:
        df["price_discount_interaction"] = df["price"] * df["discount"]

    if "competitor_pricing" in df.columns:
        df["price_vs_competitor"] = df["price"] - df["competitor_pricing"]
        df["competitor_ratio"] = df["price"] / (df["competitor_pricing"] + 1)

    if "discount" in df.columns and "holiday_promotion" in df.columns:
        holiday_numeric = pd.to_numeric(df["holiday_promotion"], errors="coerce").fillna(0)
        df["promo_discount_interaction"] = holiday_numeric * df["discount"]

    # =========================
    # ENCODAGE CATÉGORIEL
    # =========================
    categorical_cols = [
        "category", "region", "weather_condition",
        "holiday_promotion", "seasonality", "store_id", "product_id"
    ]

    existing_categorical_cols = [col for col in categorical_cols if col in df.columns]

    if existing_categorical_cols:
        for col in existing_categorical_cols:
            df[col] = df[col].astype(str)

        df = pd.get_dummies(df, columns=existing_categorical_cols, drop_first=False)

    df = df.dropna().reset_index(drop=True)
    return df