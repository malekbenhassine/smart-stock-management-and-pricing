import pandas as pd
import numpy as np

df = pd.read_csv("train_data.csv")
df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")
df = df.rename(columns={"units_sold": "sales", "inventory_level": "stock", "holiday/promotion": "holiday_promotion"})
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["store_id", "product_id", "date"])

# 1. Distribution des ventes
print("=== Distribution des ventes ===")
print(df["sales"].describe())
print(f"% de ventes < 10 : {(df['sales'] < 10).mean()*100:.1f}%")

# 2. Corrélation lag_1 → sales (le plus important)
df["lag_1"] = df.groupby(["store_id", "product_id"])["sales"].shift(1)
corr = df[["sales", "lag_1"]].corr().iloc[0, 1]
print(f"\n=== Corrélation lag_1 → sales : {corr:.4f} ===")

# 3. Variance intra-groupe
print("\n=== Variance moyenne des ventes par store×product ===")
var_within = df.groupby(["store_id", "product_id"])["sales"].std().mean()
var_total = df["sales"].std()
print(f"Std intra-groupe : {var_within:.2f}")
print(f"Std totale       : {var_total:.2f}")
print(f"Ratio signal/bruit : {var_within/var_total:.4f}")

# 4. Autocorrélation
from pandas import Series
sample = df[df["product_id"] == df["product_id"].iloc[0]]
sample = sample[sample["store_id"] == sample["store_id"].iloc[0]]["sales"]
print(f"\n=== Autocorrélation lag-1 (produit P0001, store S001) ===")
print(f"autocorr(1)  : {sample.autocorr(1):.4f}")
print(f"autocorr(7)  : {sample.autocorr(7):.4f}")
print(f"autocorr(30) : {sample.autocorr(30):.4f}")

# 5. Sample des ventes pour un groupe
print("\n=== 10 premières ventes (P0001, S001) ===")
print(sample.head(10).values)