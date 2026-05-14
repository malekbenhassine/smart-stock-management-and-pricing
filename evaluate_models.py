"""
evaluate_models.py
==================
Évaluation autonome et cohérente des modèles ML Precios.

Points corrigés :
- lecture du format Kaggle normalisé ;
- ajout de features hebdomadaires utiles sans fuite de données ;
- métriques MAE, RMSE, MAPE, WAPE, SMAPE ;
- correction du bug true_pos pour IsolationForest ;
- évaluation temporelle réelle : dernières semaines réservées au test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest
from sklearn.metrics import (
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
)
from sklearn.preprocessing import StandardScaler

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SEP = "─" * 60


def header(title: str):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def section(title: str):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def row(label: str, value, explain: str = ""):
    val_str = f"{value:.4f}" if isinstance(value, float) else str(value)
    explain_str = f"  ← {explain}" if explain else ""
    print(f"  {label:<40} {val_str}{explain_str}")


def load_csv(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        print(f"  [ERREUR] Fichier introuvable : {path}")
        sys.exit(1)
    df = pd.read_csv(path)
    print(f"  ✔ {name:<30} {len(df):>8} lignes  |  {df.shape[1]} colonnes")
    return df


def _ensure_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    """Agrège les ventes brutes en ventes hebdomadaires avec features métier connues."""
    df = sales.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")

    rename_map = {
        "date": "timestamp",
        "sales": "qty",
        "price": "unit_price",
        "inventory_level": "stock",
        "units_sold": "qty",
        "competitor_price": "competitor_pricing",
    }
    for src, dst in rename_map.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]

    required = ["timestamp", "product_id", "qty", "unit_price"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans sales.csv : {missing}")

    defaults = {
        "stock": 0,
        "discount": 0,
        "competitor_pricing": np.nan,
        "holiday_promotion": 0,
        "units_ordered": 0,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    df = _ensure_numeric(
        df,
        ["qty", "unit_price", "stock", "discount", "competitor_pricing", "holiday_promotion", "units_ordered"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time

    weekly = df.groupby(["product_id", "week"], as_index=False).agg(
        qty_week=("qty", "sum"),
        price_week=("unit_price", "mean"),
        stock_week=("stock", "mean"),
        discount_week=("discount", "mean"),
        comp_price_week=("competitor_pricing", "mean"),
        holiday_promo_week=("holiday_promotion", "max"),
        units_ordered_week=("units_ordered", "sum"),
    )

    weekly["comp_price_week"] = weekly["comp_price_week"].fillna(weekly["price_week"])
    weekly["price_gap_pct"] = (
        (weekly["price_week"] - weekly["comp_price_week"])
        / weekly["comp_price_week"].replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    weekly["is_promo_week"] = ((weekly["discount_week"] > 0) | (weekly["holiday_promo_week"] > 0)).astype(int)

    return weekly.sort_values(["product_id", "week"])


def competitor_week_median(competitor_prices: pd.DataFrame) -> pd.DataFrame:
    df = competitor_prices.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")
    if "collected_at" not in df.columns and "timestamp" in df.columns:
        df["collected_at"] = df["timestamp"]
    if "competitor_price" not in df.columns and "competitor_pricing" in df.columns:
        df["competitor_price"] = df["competitor_pricing"]

    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    df = df.dropna(subset=["collected_at"])
    df["competitor_price"] = pd.to_numeric(df["competitor_price"], errors="coerce")
    df = df.dropna(subset=["competitor_price"])
    df["week"] = df["collected_at"].dt.to_period("W").dt.start_time
    med = df.groupby(["product_id", "week"], as_index=False)["competitor_price"].median()
    return med.rename(columns={"competitor_price": "comp_median"})


def promo_flag_week(promotions: pd.DataFrame) -> pd.DataFrame:
    df = promotions.copy()
    if df.empty:
        return pd.DataFrame(columns=["product_id", "week", "promo_flag"])
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")
    for col in ["start_date", "end_date"]:
        if col not in df.columns:
            return pd.DataFrame(columns=["product_id", "week", "promo_flag"])
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df = df.dropna(subset=["start_date", "end_date"])
    rows = []
    for r in df.itertuples(index=False):
        start = pd.to_datetime(r.start_date).to_period("W").start_time
        end = pd.to_datetime(r.end_date).to_period("W").start_time
        for w in pd.date_range(start, end, freq="W-MON"):
            rows.append((int(r.product_id), pd.to_datetime(w), 1))
    if not rows:
        return pd.DataFrame(columns=["product_id", "week", "promo_flag"])
    return pd.DataFrame(rows, columns=["product_id", "week", "promo_flag"]).drop_duplicates()


def add_lag_features(df: pd.DataFrame, target_col: str, lags: int = 12) -> pd.DataFrame:
    df = df.copy().sort_values(["product_id", "week"])

    for i in range(1, lags + 1):
        df[f"lag_{i}"] = df.groupby("product_id")[target_col].shift(i)

    required_lags = [f"lag_{i}" for i in range(1, 5)]
    df = df.dropna(subset=required_lags).copy()

    product_mean = df.groupby("product_id")[target_col].transform("mean")
    for i in range(1, lags + 1):
        col = f"lag_{i}"
        df[col] = df[col].fillna(product_mean)

    df["roll_mean_4"] = df[[f"lag_{i}" for i in range(1, 5)]].mean(axis=1)
    df["roll_std_4"] = df[[f"lag_{i}" for i in range(1, 5)]].std(axis=1).fillna(0.0)
    df["roll_mean_8"] = df[[f"lag_{i}" for i in range(1, 9)]].mean(axis=1)
    df["roll_std_8"] = df[[f"lag_{i}" for i in range(1, 9)]].std(axis=1).fillna(0.0)
    df["roll_mean_12"] = df[[f"lag_{i}" for i in range(1, 13)]].mean(axis=1)
    df["roll_std_12"] = df[[f"lag_{i}" for i in range(1, 13)]].std(axis=1).fillna(0.0)
    df["velocity_ratio_4_12"] = (
        df["roll_mean_4"] / df["roll_mean_12"].replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(1.0)

    df["weekofyear"] = pd.to_datetime(df["week"]).dt.isocalendar().week.astype(int)
    df["month"] = pd.to_datetime(df["week"]).dt.month.astype(int)
    df["quarter"] = pd.to_datetime(df["week"]).dt.quarter.astype(int)

    if "stock_week" in df.columns:
        df["stock_coverage_weeks"] = (
            df["stock_week"] / df["roll_mean_4"].replace(0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).fillna(999).clip(0, 999)
    else:
        df["stock_coverage_weeks"] = 999

    return df.replace([np.inf, -np.inf], np.nan).fillna(0)


def train_quantile_gbr(X, y, alpha: float, n_estimators: int = 400) -> GradientBoostingRegressor:
    model = GradientBoostingRegressor(
        loss="quantile",
        alpha=alpha,
        n_estimators=n_estimators,
        learning_rate=0.04,
        max_depth=3,
        random_state=42,
    )
    model.fit(X, y)
    return model


def mape_safe(y_true, y_pred) -> float:
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    mask = y_true != 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)


def wape_safe(y_true, y_pred) -> float:
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    denom = np.sum(np.abs(y_true))
    if denom == 0:
        return 0.0
    return float(np.sum(np.abs(y_true - y_pred)) / denom * 100.0)


def smape_safe(y_true, y_pred) -> float:
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2.0
    mask = denom != 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100.0)


def time_split(df: pd.DataFrame, test_ratio: float = 0.2):
    weeks = sorted(df["week"].unique())
    split_idx = int(len(weeks) * (1 - test_ratio))
    train_weeks = set(weeks[:split_idx])
    test_weeks = set(weeks[split_idx:])
    return (
        df[df["week"].isin(train_weeks)].copy(),
        df[df["week"].isin(test_weeks)].copy(),
        len(train_weeks),
        len(test_weeks),
    )


COMMON_FEATURES = [
    "product_id",
    "price_week",
    "stock_week",
    "discount_week",
    "comp_price_week",
    "price_gap_pct",
    "is_promo_week",
    "holiday_promo_week",
    "units_ordered_week",
    "weekofyear",
    "month",
    "quarter",
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_4",
    "lag_8",
    "lag_12",
    "roll_mean_4",
    "roll_std_4",
    "roll_mean_8",
    "roll_std_8",
    "roll_mean_12",
    "roll_std_12",
    "velocity_ratio_4_12",
    "stock_coverage_weeks",
]


def _print_regression_results(y_test, y_p50, y_p05, y_p95):
    mae = mean_absolute_error(y_test, y_p50)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_p50)))
    mape = mape_safe(y_test, y_p50)
    wape = wape_safe(y_test, y_p50)
    smape = smape_safe(y_test, y_p50)
    coverage = float(((y_test >= y_p05) & (y_test <= y_p95)).mean() * 100)
    width = float(np.mean(y_p95 - y_p05))

    row("MAE  (unités)", mae, "erreur absolue moyenne")
    row("RMSE (unités)", rmse, "pénalise davantage les grosses erreurs")
    row("MAPE (%)", mape, "erreur en %. Attention aux faibles volumes")
    row("WAPE (%)", wape, "erreur pondérée par le volume total vendu")
    row("SMAPE (%)", smape, "erreur symétrique plus stable")
    row("Couverture [p05,p95] %", coverage, "% des vraies valeurs dans l'intervalle élargi")
    row("Largeur intervalle moy", width, "largeur moyenne de l'incertitude")
    return {"mae": mae, "rmse": rmse, "mape": mape, "wape": wape, "smape": smape, "coverage": coverage}


def _fit_quantiles(train_df, test_df, feature_cols, target_col):
    X_train = train_df[feature_cols].values.astype(float)
    y_train = train_df[target_col].values.astype(float)
    X_test = test_df[feature_cols].values.astype(float)
    y_test = test_df[target_col].values.astype(float)

    print("\n  Entraînement p05 / p50 / p95 sur les données train...")
    m_p05 = train_quantile_gbr(X_train, y_train, alpha=0.05)
    m_p50 = train_quantile_gbr(X_train, y_train, alpha=0.50)
    m_p95 = train_quantile_gbr(X_train, y_train, alpha=0.95)

    y_p05 = np.maximum(0, m_p05.predict(X_test))
    y_p50 = np.maximum(0, m_p50.predict(X_test))
    y_p95 = np.maximum(0, m_p95.predict(X_test))
    y_p05 = np.minimum(y_p05, y_p50)
    y_p95 = np.maximum(y_p95, y_p50)
    return y_test, y_p05, y_p50, y_p95


def evaluate_demand():
    header("MODÈLE 1 — Prévision de demande hebdomadaire")
    section("Chargement des données")
    sales = load_csv("sales.csv")
    weekly = build_weekly_sales(sales)
    df = add_lag_features(weekly, target_col="qty_week", lags=12)
    df = df.rename(columns={"qty_week": "qty"})
    feature_cols = [c for c in COMMON_FEATURES if c in df.columns]

    section("Statistiques du dataset")
    row("Ventes brutes (lignes)", len(sales))
    row("Semaines agrégées (lignes)", len(weekly))
    row("Lignes supervisées (après lag)", len(df))
    row("Produits uniques", df["product_id"].nunique())
    row("Semaines couvertes", df["week"].nunique())
    row("Features utilisées", len(feature_cols))
    row("Période", f"{pd.to_datetime(df['week']).min().date()}  →  {pd.to_datetime(df['week']).max().date()}")

    train_df, test_df, n_train_weeks, n_test_weeks = time_split(df, test_ratio=0.2)
    section("Split train / test (temporel, 80/20)")
    row("Semaines train", n_train_weeks)
    row("Semaines test", n_test_weeks)
    row("Lignes train", len(train_df))
    row("Lignes test", len(test_df))

    y_test, y_p05, y_p50, y_p95 = _fit_quantiles(train_df, test_df, feature_cols, "qty")
    section("Résultats sur le jeu de TEST (données non vues)")
    metrics = _print_regression_results(y_test, y_p50, y_p05, y_p95)

    print("\n  INTERPRÉTATION")
    if metrics["wape"] < 10:
        print("  ✅ WAPE excellent (< 10%) — très bon niveau opérationnel.")
    elif metrics["wape"] < 20:
        print("  ✅ WAPE bon (< 20%) — modèle exploitable avec garde-fou métier.")
    elif metrics["wape"] < 35:
        print("  ⚠️  WAPE acceptable (< 35%) — encore améliorable.")
    else:
        print("  ❌ WAPE élevé — enrichir les données/features.")


def build_anomaly_dataset(products: pd.DataFrame, competitor_prices: pd.DataFrame) -> pd.DataFrame:
    prod = products.copy()
    prod.columns = prod.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")
    comp = competitor_prices.copy()
    comp.columns = comp.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")
    prod = prod[["product_id", "current_price"]].copy()
    df = comp.merge(prod, on="product_id", how="left").copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    df = df.dropna(subset=["collected_at"])
    if "status" not in df.columns:
        df["status"] = "OK"
    df = df.sort_values(["product_id", "competitor_id", "collected_at"])
    df["status_bad"] = (df["status"].astype(str).str.upper() != "OK").astype(int)
    df["ratio"] = df["competitor_price"] / df["current_price"].replace(0, np.nan)
    df["ratio"] = df["ratio"].fillna(1.0)
    df["log_ratio"] = np.log(np.clip(df["ratio"], 1e-6, 1e6))
    df["prev_price"] = df.groupby(["product_id", "competitor_id"])["competitor_price"].shift(1)
    df["delta_pct"] = (df["competitor_price"] - df["prev_price"]) / df["prev_price"]
    df["delta_pct"] = df["delta_pct"].replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-2, 2)
    df["prev_time"] = df.groupby(["product_id", "competitor_id"])["collected_at"].shift(1)
    df["gap_hours"] = (df["collected_at"] - df["prev_time"]).dt.total_seconds() / 3600.0
    df["gap_hours"] = df["gap_hours"].fillna(df["gap_hours"].median() if df["gap_hours"].notna().any() else 0.0).clip(lower=0)
    df["gap_hours_log"] = np.log1p(df["gap_hours"])
    return df.dropna()


def evaluate_anomaly():
    header("MODÈLE 2 — Détection d'anomalies (IsolationForest)")
    section("Chargement des données")
    products = load_csv("products.csv")
    competitor_prices = load_csv("competitor_prices.csv")
    df = build_anomaly_dataset(products, competitor_prices)

    section("Statistiques du dataset")
    row("Lignes après construction features", len(df))
    row("Produits uniques", df["product_id"].nunique())
    row("Concurrents uniques", df["competitor_id"].nunique())

    df["is_anomaly"] = (
        (df["status_bad"] == 1)
        | (np.abs(df["delta_pct"]) > 0.5)
        | (np.abs(df["log_ratio"]) > np.log(1.5))
    ).astype(int)
    n_anomalies = int(df["is_anomaly"].sum())
    row("Anomalies dans le dataset (vérité)", n_anomalies, f"{(n_anomalies / max(len(df), 1) * 100):.1f}% du total")

    if len(df) < 100:
        print("  ⚠️  Pas assez de données pour évaluer IsolationForest.")
        return

    feature_cols = ["log_ratio", "delta_pct", "gap_hours_log", "status_bad"]
    dates = sorted(df["collected_at"].unique())
    split_idx = int(len(dates) * 0.8)
    split_date = dates[split_idx]
    train_df = df[df["collected_at"] < split_date].copy()
    test_df = df[df["collected_at"] >= split_date].copy()

    section("Split train / test (temporel, 80/20)")
    row("Lignes train", len(train_df))
    row("Lignes test", len(test_df))
    row("Anomalies dans test", int(test_df["is_anomaly"].sum()))

    X_train = train_df[feature_cols].values.astype(float)
    X_test = test_df[feature_cols].values.astype(float)
    y_true = test_df["is_anomaly"].values
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)
    iforest = IsolationForest(n_estimators=400, contamination=0.02, random_state=42)
    iforest.fit(X_train_s)
    scores = iforest.decision_function(X_test_s)
    threshold = float(np.quantile(iforest.decision_function(X_train_s), 0.05))
    y_pred = (scores < threshold).astype(int)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    detected = int(y_pred.sum())
    true_pos = int(((y_pred == 1) & (y_true == 1)).sum())
    section("Résultats sur le jeu de TEST (données non vues)")
    row("Anomalies détectées par le modèle", detected)
    row("Vrais positifs", true_pos)
    row("Précision", prec)
    row("Rappel", rec)
    row("F1-score", f1)


def evaluate_price():
    header("MODÈLE 3 — Recommandation de prix")
    section("Chargement des données")
    sales = load_csv("sales.csv")
    competitor_prices = load_csv("competitor_prices.csv")
    promotions = load_csv("promotions.csv")
    weekly = build_weekly_sales(sales)
    comp = competitor_week_median(competitor_prices)
    promo = promo_flag_week(promotions)
    df = weekly.merge(comp, on=["product_id", "week"], how="left")
    df = df.merge(promo, on=["product_id", "week"], how="left")
    df["promo_flag"] = df["promo_flag"].fillna(0).astype(int)
    df["comp_median"] = df["comp_median"].fillna(df["price_week"])
    df["price"] = df["price_week"].astype(float)
    df = add_lag_features(df, target_col="qty_week", lags=12)
    feature_cols = [c for c in ["price", "comp_median", "promo_flag"] + COMMON_FEATURES if c in df.columns]

    section("Statistiques du dataset")
    row("Lignes supervisées", len(df))
    row("Produits uniques", df["product_id"].nunique())
    row("Semaines couvertes", df["week"].nunique())
    row("Features utilisées", len(feature_cols))
    train_df, test_df, n_train_weeks, n_test_weeks = time_split(df, test_ratio=0.2)
    section("Split train / test (temporel, 80/20)")
    row("Semaines train", n_train_weeks)
    row("Semaines test", n_test_weeks)
    row("Lignes train", len(train_df))
    row("Lignes test", len(test_df))
    y_test, y_p05, y_p50, y_p95 = _fit_quantiles(train_df, test_df, feature_cols, "qty_week")
    section("Résultats sur le jeu de TEST (données non vues)")
    _print_regression_results(y_test, y_p50, y_p05, y_p95)


def evaluate_promo():
    header("MODÈLE 4 — Recommandation promotionnelle")
    section("Chargement des données")
    sales = load_csv("sales.csv")
    competitor_prices = load_csv("competitor_prices.csv")
    promotions = load_csv("promotions.csv")
    weekly = build_weekly_sales(sales)
    comp = competitor_week_median(competitor_prices)
    promo = promo_flag_week(promotions)
    df = weekly.merge(comp, on=["product_id", "week"], how="left")
    df = df.merge(promo, on=["product_id", "week"], how="left")
    df["comp_median"] = df["comp_median"].fillna(df["price_week"])
    df["promo_flag"] = df["promo_flag"].fillna(0).astype(int)
    df["discount"] = df["discount_week"].fillna(0.0)
    df = add_lag_features(df, target_col="qty_week", lags=12)
    feature_cols = [c for c in ["comp_median", "promo_flag", "discount"] + COMMON_FEATURES if c in df.columns]

    section("Statistiques du dataset")
    row("Lignes supervisées", len(df))
    row("Produits uniques", df["product_id"].nunique())
    row("Semaines avec promo active", int((df["promo_flag"] == 1).sum()), f"sur {len(df)} lignes")
    row("Features utilisées", len(feature_cols))
    train_df, test_df, n_train_weeks, n_test_weeks = time_split(df, test_ratio=0.2)
    section("Split train / test (temporel, 80/20)")
    row("Semaines train", n_train_weeks)
    row("Semaines test", n_test_weeks)
    row("Lignes train", len(train_df))
    row("Lignes test", len(test_df))
    y_test, y_p05, y_p50, y_p95 = _fit_quantiles(train_df, test_df, feature_cols, "qty_week")
    section("Résultats sur le jeu de TEST (données non vues)")
    _print_regression_results(y_test, y_p50, y_p05, y_p95)

    test_df = test_df.copy()
    test_df["y_pred_p50"] = y_p50
    test_df["abs_error"] = np.abs(y_p50 - y_test)
    mae_promo = test_df[test_df["promo_flag"] == 1]["abs_error"].mean() if (test_df["promo_flag"] == 1).any() else float("nan")
    mae_no_promo = test_df[test_df["promo_flag"] == 0]["abs_error"].mean() if (test_df["promo_flag"] == 0).any() else float("nan")
    if not np.isnan(mae_promo):
        row("MAE semaines AVEC promo", float(mae_promo))
    if not np.isnan(mae_no_promo):
        row("MAE semaines SANS promo", float(mae_no_promo))


def main():
    parser = argparse.ArgumentParser(description="Évaluation des modèles ML Precios — split temporel 80/20")
    parser.add_argument("--model", choices=["demand", "anomaly", "price", "promo", "all"], default="all")
    args = parser.parse_args()
    print(f"\n{'█' * 60}")
    print("  ÉVALUATION DES MODÈLES ML — PRECIOS")
    print(f"  Data directory : {DATA_DIR}")
    print(f"{'█' * 60}")
    if not DATA_DIR.exists():
        print(f"\n  [ERREUR] Le dossier /data est introuvable : {DATA_DIR}")
        sys.exit(1)
    models = {"demand": evaluate_demand, "anomaly": evaluate_anomaly, "price": evaluate_price, "promo": evaluate_promo}
    to_run = list(models.keys()) if args.model == "all" else [args.model]
    for name in to_run:
        try:
            models[name]()
        except Exception as e:
            print(f"\n  [ERREUR] Modèle '{name}' : {e}")
    print(f"\n{'█' * 60}")
    print("  ÉVALUATION TERMINÉE")
    print(f"{'█' * 60}\n")


if __name__ == "__main__":
    main()
