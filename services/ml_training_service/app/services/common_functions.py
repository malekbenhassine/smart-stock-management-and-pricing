import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor


def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    df = sales.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time

    weekly = df.groupby(["product_id", "week"], as_index=False).agg(
        qty_week=("qty", "sum"),
        price_week=("unit_price", "mean"),
    )

    return weekly.sort_values(["product_id", "week"])


def competitor_week_median(competitor_prices: pd.DataFrame) -> pd.DataFrame:
    df = competitor_prices.copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    df["week"] = df["collected_at"].dt.to_period("W").dt.start_time

    median_df = df.groupby(["product_id", "week"], as_index=False)["competitor_price"].median()
    return median_df.rename(columns={"competitor_price": "comp_median"})


def promo_flag_week(promotions: pd.DataFrame) -> pd.DataFrame:
    df = promotions.copy()

    if df.empty:
        return pd.DataFrame(columns=["product_id", "week", "promo_flag"])

    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])

    rows = []

    for row in df.itertuples(index=False):
        start = pd.to_datetime(row.start_date).to_period("W").start_time
        end = pd.to_datetime(row.end_date).to_period("W").start_time
        weeks = pd.date_range(start, end, freq="W-MON")

        for week in weeks:
            rows.append((int(row.product_id), pd.to_datetime(week), 1))

    return pd.DataFrame(rows, columns=["product_id", "week", "promo_flag"]).drop_duplicates()


def add_lag_features(df: pd.DataFrame, target_col: str, lags: int = 4) -> pd.DataFrame:
    df = df.copy().sort_values(["product_id", "week"])

    for i in range(1, lags + 1):
        df[f"lag_{i}"] = df.groupby("product_id")[target_col].shift(i)

    lag_cols = [f"lag_{i}" for i in range(1, lags + 1)]
    df = df.dropna(subset=lag_cols).copy()

    df["roll_mean_4"] = df[lag_cols].mean(axis=1)
    df["roll_std_4"] = df[lag_cols].std(axis=1).fillna(0.0)
    df["weekofyear"] = pd.to_datetime(df["week"]).dt.isocalendar().week.astype(int)

    return df


def train_quantile_gbr(X, y, alpha: float, n_estimators: int = 400) -> GradientBoostingRegressor:
    model = GradientBoostingRegressor(
        loss="quantile",
        alpha=alpha,
        n_estimators=n_estimators,
        learning_rate=0.05,
        max_depth=3,
        random_state=42,
    )
    model.fit(X, y)
    return model