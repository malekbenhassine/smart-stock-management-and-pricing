import pandas as pd

def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    df = sales.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time
    weekly = df.groupby(["product_id", "week"], as_index=False)["qty"].sum()
    return weekly.sort_values(["product_id", "week"])