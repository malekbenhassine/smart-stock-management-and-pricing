"""
evaluate_models.py
==================
Script d'évaluation autonome pour tous les modèles ML du projet Precios.

UTILISATION :
    python evaluate_models.py

    # Évaluer un seul modèle :
    python evaluate_models.py --model demand
    python evaluate_models.py --model anomaly
    python evaluate_models.py --model price
    python evaluate_models.py --model promo

EMPLACEMENT : à placer à la racine du projet (même niveau que /services et /data)
"""

import argparse
import json
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

# ─── Chemins ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# ─── Helpers d'affichage ────────────────────────────────────────────────────
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


# ─── Loaders CSV ────────────────────────────────────────────────────────────

def load_csv(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        print(f"  [ERREUR] Fichier introuvable : {path}")
        sys.exit(1)
    df = pd.read_csv(path)
    print(f"  ✔ {name:<30} {len(df):>8} lignes  |  {df.shape[1]} colonnes")
    return df


# ─── Fonctions communes ──────────────────────────────────────────────────────

def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    """Agrège les ventes brutes en ventes hebdomadaires par produit."""
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
    med = df.groupby(["product_id", "week"], as_index=False)["competitor_price"].median()
    return med.rename(columns={"competitor_price": "comp_median"})


def promo_flag_week(promotions: pd.DataFrame) -> pd.DataFrame:
    df = promotions.copy()
    if df.empty:
        return pd.DataFrame(columns=["product_id", "week", "promo_flag"])
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    rows = []
    for r in df.itertuples(index=False):
        start = pd.to_datetime(r.start_date).to_period("W").start_time
        end = pd.to_datetime(r.end_date).to_period("W").start_time
        for w in pd.date_range(start, end, freq="W-MON"):
            rows.append((int(r.product_id), pd.to_datetime(w), 1))
    if not rows:
        return pd.DataFrame(columns=["product_id", "week", "promo_flag"])
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


def train_quantile_gbr(X, y, alpha: float, n_estimators: int = 300) -> GradientBoostingRegressor:
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


def mape_safe(y_true, y_pred) -> float:
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    mask = y_true != 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)


def time_split(df: pd.DataFrame, test_ratio: float = 0.2):
    """
    Split temporel : les dernières semaines (20%) = test.
    Les premières semaines (80%) = train.
    Respecte l'ordre chronologique — aucune fuite de données.
    """
    weeks = sorted(df["week"].unique())
    split_idx = int(len(weeks) * (1 - test_ratio))
    train_weeks = set(weeks[:split_idx])
    test_weeks  = set(weeks[split_idx:])
    return (
        df[df["week"].isin(train_weeks)].copy(),
        df[df["week"].isin(test_weeks)].copy(),
        len(train_weeks),
        len(test_weeks),
    )


# ════════════════════════════════════════════════════════════════════════════
#  MODÈLE 1 — DEMANDE HEBDOMADAIRE (GradientBoostingRegressor, 3 quantiles)
# ════════════════════════════════════════════════════════════════════════════

def evaluate_demand():
    header("MODÈLE 1 — Prévision de demande hebdomadaire")

    section("Chargement des données")
    sales = load_csv("sales.csv")

    # ── Construction du dataset supervisé ──
    weekly = build_weekly_sales(sales)

    df = weekly.copy().sort_values(["product_id", "week"])
    for i in range(1, 5):
        df[f"lag_{i}"] = df.groupby("product_id")["qty_week"].shift(i)
    lag_cols = [f"lag_{i}" for i in range(1, 5)]
    df = df.dropna(subset=lag_cols).copy()
    df["roll_mean_4"] = df[lag_cols].mean(axis=1)
    df["roll_std_4"]  = df[lag_cols].std(axis=1).fillna(0.0)
    df["weekofyear"]  = pd.to_datetime(df["week"]).dt.isocalendar().week.astype(int)
    df = df.rename(columns={"qty_week": "qty"})

    feature_cols = ["product_id", "price_week", "weekofyear",
                    "lag_1", "lag_2", "lag_3", "lag_4", "roll_mean_4", "roll_std_4"]

    section("Statistiques du dataset")
    row("Ventes brutes (lignes)",       len(sales))
    row("Semaines agrégées (lignes)",   len(weekly))
    row("Lignes supervisées (après lag)", len(df))
    row("Produits uniques",             df["product_id"].nunique())
    row("Semaines couvertes",           df["week"].nunique())
    row("Période",
        f"{pd.to_datetime(df['week']).min().date()}  →  {pd.to_datetime(df['week']).max().date()}")

    # ── Split temporel ──
    train_df, test_df, n_train_weeks, n_test_weeks = time_split(df, test_ratio=0.2)

    section("Split train / test (temporel, 80/20)")
    row("Semaines train",  n_train_weeks)
    row("Semaines test",   n_test_weeks)
    row("Lignes train",    len(train_df))
    row("Lignes test",     len(test_df))
    print(f"\n  [IMPORTANT] Le modèle N'A PAS VU les {n_test_weeks} dernières semaines.")

    # ── Entraînement sur train uniquement ──
    X_train = train_df[feature_cols].values.astype(float)
    y_train = train_df["qty"].values.astype(float)
    X_test  = test_df[feature_cols].values.astype(float)
    y_test  = test_df["qty"].values.astype(float)

    print("\n  Entraînement p10 / p50 / p90 sur les données train...")
    m_p10 = train_quantile_gbr(X_train, y_train, alpha=0.10)
    m_p50 = train_quantile_gbr(X_train, y_train, alpha=0.50)
    m_p90 = train_quantile_gbr(X_train, y_train, alpha=0.90)

    y_p10 = np.maximum(0, m_p10.predict(X_test))
    y_p50 = np.maximum(0, m_p50.predict(X_test))
    y_p90 = np.maximum(0, m_p90.predict(X_test))

    # ── Métriques ──
    mae  = mean_absolute_error(y_test, y_p50)
    rmse = np.sqrt(mean_squared_error(y_test, y_p50))
    mape = mape_safe(y_test, y_p50)
    coverage = float(((y_test >= y_p10) & (y_test <= y_p90)).mean() * 100)
    width    = float(np.mean(y_p90 - y_p10))

    section("Résultats sur le jeu de TEST (données non vues)")
    row("MAE  (unités)",          mae,      "erreur absolue moyenne sur les quantités prédites (p50)")
    row("RMSE (unités)",          rmse,     "pénalise davantage les grosses erreurs")
    row("MAPE (%)",               mape,     "erreur en %. < 20% = bon, < 10% = excellent")
    row("Couverture [p10,p90] %", coverage, "% de vraies valeurs dans l'intervalle prédit. Cible ≥ 80%")
    row("Largeur intervalle moy", width,    "plus l'intervalle est large, moins le modèle est précis")

    print(f"\n  {'INTERPRÉTATION':}")
    if mape < 10:
        print("  ✅ MAPE excellent (< 10%) — le modèle prédit très bien la demande.")
    elif mape < 20:
        print("  ✅ MAPE bon (< 20%) — le modèle est fiable pour les décisions opérationnelles.")
    elif mape < 35:
        print("  ⚠️  MAPE acceptable (< 35%) — marge d'amélioration possible (plus de données, features).")
    else:
        print("  ❌ MAPE élevé (> 35%) — le modèle manque de données ou de features pertinentes.")

    if coverage >= 80:
        print(f"  ✅ Couverture {coverage:.1f}% ≥ 80% — l'intervalle [p10,p90] est bien calibré.")
    else:
        print(f"  ⚠️  Couverture {coverage:.1f}% < 80% — l'intervalle sous-estime l'incertitude.")


# ════════════════════════════════════════════════════════════════════════════
#  MODÈLE 2 — ANOMALIES (IsolationForest non supervisé)
# ════════════════════════════════════════════════════════════════════════════

def build_anomaly_dataset(products: pd.DataFrame, competitor_prices: pd.DataFrame) -> pd.DataFrame:
    prod = products[["product_id", "current_price"]].copy()
    df = competitor_prices.merge(prod, on="product_id", how="left").copy()
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    df = df.sort_values(["product_id", "competitor_id", "collected_at"])

    df["status_bad"] = (df["status"] != "OK").astype(int)
    df["ratio"]      = df["competitor_price"] / df["current_price"].replace(0, np.nan)
    df["ratio"]      = df["ratio"].fillna(1.0)
    df["log_ratio"]  = np.log(np.clip(df["ratio"], 1e-6, 1e6))

    df["prev_price"] = df.groupby(["product_id", "competitor_id"])["competitor_price"].shift(1)
    df["delta_pct"]  = (df["competitor_price"] - df["prev_price"]) / df["prev_price"]
    df["delta_pct"]  = df["delta_pct"].replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-2, 2)

    df["prev_time"]       = df.groupby(["product_id", "competitor_id"])["collected_at"].shift(1)
    df["gap_hours"]       = (df["collected_at"] - df["prev_time"]).dt.total_seconds() / 3600.0
    df["gap_hours"]       = df["gap_hours"].fillna(df["gap_hours"].median() if df["gap_hours"].notna().any() else 0.0)
    df["gap_hours"]       = df["gap_hours"].clip(lower=0)
    df["gap_hours_log"]   = np.log1p(df["gap_hours"])

    return df.dropna()


def evaluate_anomaly():
    header("MODÈLE 2 — Détection d'anomalies (IsolationForest)")

    section("Chargement des données")
    products         = load_csv("products.csv")
    competitor_prices = load_csv("competitor_prices.csv")

    df = build_anomaly_dataset(products, competitor_prices)

    section("Statistiques du dataset")
    row("Lignes après construction features", len(df))
    row("Produits uniques",                  df["product_id"].nunique())
    row("Concurrents uniques",               df["competitor_id"].nunique())

    # ── Vérité terrain approchée ──
    # (même logique que anomaly_evaluator.py existant)
    df["is_anomaly"] = (
        (df["status_bad"] == 1)
        | (np.abs(df["delta_pct"]) > 0.5)
        | (np.abs(df["log_ratio"]) > np.log(1.5))
    ).astype(int)

    n_anomalies = int(df["is_anomaly"].sum())
    pct_anomalies = n_anomalies / len(df) * 100
    row("Anomalies dans le dataset (vérité)", n_anomalies, f"{pct_anomalies:.1f}% du total")

    feature_cols = ["log_ratio", "delta_pct", "gap_hours_log", "status_bad"]

    # ── Split temporel (80% train / 20% test) ──
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    dates = sorted(df["collected_at"].unique())
    split_idx = int(len(dates) * 0.8)
    split_date = dates[split_idx]

    train_df = df[df["collected_at"] < split_date].copy()
    test_df  = df[df["collected_at"] >= split_date].copy()

    section("Split train / test (temporel, 80/20)")
    row("Lignes train",  len(train_df))
    row("Lignes test",   len(test_df))
    row("Anomalies dans test", int(test_df["is_anomaly"].sum()))
    print(f"\n  [IMPORTANT] Le modèle N'A PAS VU les données après {pd.to_datetime(split_date).date()}")

    # ── Entraînement sur train uniquement ──
    X_train = train_df[feature_cols].values.astype(float)
    X_test  = test_df[feature_cols].values.astype(float)
    y_true  = test_df["is_anomaly"].values

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)  # fit SEULEMENT sur train
    X_test_s  = scaler.transform(X_test)        # transform test avec le même scaler

    print("\n  Entraînement IsolationForest sur les données train...")
    iforest = IsolationForest(n_estimators=400, contamination=0.02, random_state=42)
    iforest.fit(X_train_s)

    scores  = iforest.decision_function(X_test_s)
    threshold = float(np.quantile(iforest.decision_function(X_train_s), 0.05))
    y_pred  = (scores < threshold).astype(int)

    prec = precision_score(y_true, y_pred, zero_division=0)
    rec  = recall_score(y_true,  y_pred, zero_division=0)
    f1   = f1_score(y_true,    y_pred, zero_division=0)

    detected     = int(y_pred.sum())
    true_pos     = int((y_pred == 1) & (y_true == 1)).sum() if hasattr(y_pred, '__iter__') else 0
    true_pos     = int(((y_pred == 1) & (y_true == 1)).sum())

    section("Résultats sur le jeu de TEST (données non vues)")
    row("Anomalies détectées par le modèle", detected)
    row("Vrais positifs",                   true_pos)
    row("Précision",  prec, "parmi les anomalies détectées, combien sont vraies. Cible > 0.7")
    row("Rappel",     rec,  "parmi les vraies anomalies, combien détectées. Cible > 0.5")
    row("F1-score",   f1,   "harmonie précision/rappel. Cible > 0.6")

    print(f"\n  INTERPRÉTATION :")
    if f1 >= 0.7:
        print("  ✅ F1 excellent (≥ 0.7) — le modèle détecte bien les anomalies.")
    elif f1 >= 0.5:
        print("  ✅ F1 correct (≥ 0.5) — acceptable pour un modèle non supervisé.")
    else:
        print("  ⚠️  F1 faible — normal pour IsolationForest sans labels réels.")
        print("       La vérité terrain utilisée ici est approximative (règles heuristiques).")


# ════════════════════════════════════════════════════════════════════════════
#  MODÈLE 3 — RECOMMANDATION DE PRIX (GBR quantile + features concurrents)
# ════════════════════════════════════════════════════════════════════════════

def evaluate_price():
    header("MODÈLE 3 — Recommandation de prix")

    section("Chargement des données")
    sales             = load_csv("sales.csv")
    competitor_prices = load_csv("competitor_prices.csv")
    promotions        = load_csv("promotions.csv")

    weekly = build_weekly_sales(sales)
    comp   = competitor_week_median(competitor_prices)
    promo  = promo_flag_week(promotions)

    df = weekly.merge(comp,   on=["product_id", "week"], how="left")
    df = df.merge(promo, on=["product_id", "week"], how="left")
    df["promo_flag"]  = df["promo_flag"].fillna(0).astype(int)
    df["comp_median"] = df["comp_median"].fillna(df["price_week"])
    df["price"]       = df["price_week"].astype(float)
    df = add_lag_features(df, target_col="qty_week", lags=4)

    feature_cols = ["product_id", "price", "comp_median", "promo_flag",
                    "lag_1", "lag_2", "lag_3", "lag_4", "roll_mean_4", "roll_std_4", "weekofyear"]

    section("Statistiques du dataset")
    row("Lignes supervisées", len(df))
    row("Produits uniques",   df["product_id"].nunique())
    row("Semaines couvertes", df["week"].nunique())

    # ── Split temporel ──
    train_df, test_df, n_train_weeks, n_test_weeks = time_split(df, test_ratio=0.2)

    section("Split train / test (temporel, 80/20)")
    row("Semaines train", n_train_weeks)
    row("Semaines test",  n_test_weeks)
    row("Lignes train",   len(train_df))
    row("Lignes test",    len(test_df))

    X_train = train_df[feature_cols].values.astype(float)
    y_train = train_df["qty_week"].values.astype(float)
    X_test  = test_df[feature_cols].values.astype(float)
    y_test  = test_df["qty_week"].values.astype(float)

    print("\n  Entraînement p10 / p50 / p90 sur les données train...")
    m_p50 = train_quantile_gbr(X_train, y_train, alpha=0.50)
    m_p10 = train_quantile_gbr(X_train, y_train, alpha=0.10)
    m_p90 = train_quantile_gbr(X_train, y_train, alpha=0.90)

    y_p50 = np.maximum(0, m_p50.predict(X_test))
    y_p10 = np.maximum(0, m_p10.predict(X_test))
    y_p90 = np.maximum(0, m_p90.predict(X_test))

    mae      = mean_absolute_error(y_test, y_p50)
    rmse     = np.sqrt(mean_squared_error(y_test, y_p50))
    mape     = mape_safe(y_test, y_p50)
    coverage = float(((y_test >= y_p10) & (y_test <= y_p90)).mean() * 100)

    section("Résultats sur le jeu de TEST (données non vues)")
    row("MAE  (unités vendues)", mae,      "erreur absolue moyenne sur la demande prédite")
    row("RMSE (unités vendues)", rmse,     "pénalise les grosses erreurs")
    row("MAPE (%)",              mape,     "erreur moyenne en pourcentage. Cible < 20%")
    row("Couverture [p10,p90]",  coverage, "% de vraies valeurs dans l'intervalle. Cible ≥ 80%")

    print(f"\n  INTERPRÉTATION :")
    if mape < 20:
        print("  ✅ Le modèle de prix prédit la demande avec une bonne précision.")
    else:
        print("  ⚠️  MAPE > 20% — la prédiction de demande pour la recommandation de prix")
        print("       peut être améliorée (données prix concurrents plus denses, plus de lags).")


# ════════════════════════════════════════════════════════════════════════════
#  MODÈLE 4 — RECOMMANDATION PROMOTIONNELLE (GBR quantile)
# ════════════════════════════════════════════════════════════════════════════

def evaluate_promo():
    header("MODÈLE 4 — Recommandation promotionnelle")

    section("Chargement des données")
    sales             = load_csv("sales.csv")
    competitor_prices = load_csv("competitor_prices.csv")
    promotions        = load_csv("promotions.csv")

    weekly = build_weekly_sales(sales)
    comp   = competitor_week_median(competitor_prices)
    promo  = promo_flag_week(promotions)

    df = weekly.merge(comp,   on=["product_id", "week"], how="left")
    df = df.merge(promo, on=["product_id", "week"], how="left")
    df["comp_median"] = df["comp_median"].fillna(df["price_week"])
    df["promo_flag"]  = df["promo_flag"].fillna(0).astype(int)
    df["discount"]    = 0.0
    df = add_lag_features(df, target_col="qty_week", lags=4)

    feature_cols = ["product_id", "price_week", "comp_median", "promo_flag", "discount",
                    "lag_1", "lag_2", "lag_3", "lag_4", "roll_mean_4", "roll_std_4", "weekofyear"]

    section("Statistiques du dataset")
    row("Lignes supervisées",          len(df))
    row("Produits uniques",            df["product_id"].nunique())
    row("Semaines avec promo active",  int((df["promo_flag"] == 1).sum()),
        f"sur {len(df)} lignes totales")

    # ── Split temporel ──
    train_df, test_df, n_train_weeks, n_test_weeks = time_split(df, test_ratio=0.2)

    section("Split train / test (temporel, 80/20)")
    row("Semaines train", n_train_weeks)
    row("Semaines test",  n_test_weeks)
    row("Lignes train",   len(train_df))
    row("Lignes test",    len(test_df))

    X_train = train_df[feature_cols].values.astype(float)
    y_train = train_df["qty_week"].values.astype(float)
    X_test  = test_df[feature_cols].values.astype(float)
    y_test  = test_df["qty_week"].values.astype(float)

    print("\n  Entraînement p10 / p50 / p90 sur les données train...")
    m_p50 = train_quantile_gbr(X_train, y_train, alpha=0.50)
    m_p10 = train_quantile_gbr(X_train, y_train, alpha=0.10)
    m_p90 = train_quantile_gbr(X_train, y_train, alpha=0.90)

    y_p50 = np.maximum(0, m_p50.predict(X_test))
    y_p10 = np.maximum(0, m_p10.predict(X_test))
    y_p90 = np.maximum(0, m_p90.predict(X_test))

    mae      = mean_absolute_error(y_test, y_p50)
    rmse     = np.sqrt(mean_squared_error(y_test, y_p50))
    mape     = mape_safe(y_test, y_p50)
    coverage = float(((y_test >= y_p10) & (y_test <= y_p90)).mean() * 100)

    # Analyse promo vs non-promo
    test_df = test_df.copy()
    test_df["y_pred_p50"] = y_p50
    test_df["abs_error"]  = np.abs(y_p50 - y_test)
    mae_promo    = test_df[test_df["promo_flag"] == 1]["abs_error"].mean() if (test_df["promo_flag"] == 1).any() else float("nan")
    mae_no_promo = test_df[test_df["promo_flag"] == 0]["abs_error"].mean()

    section("Résultats sur le jeu de TEST (données non vues)")
    row("MAE  globale (unités)", mae,      "erreur absolue moyenne")
    row("RMSE globale (unités)", rmse,     "pénalise les grosses erreurs")
    row("MAPE globale (%)",      mape,     "erreur en pourcentage")
    row("Couverture [p10,p90]",  coverage, "% valeurs dans l'intervalle")
    if not np.isnan(mae_promo):
        row("MAE semaines AVEC promo",    mae_promo,    "précision du modèle pendant les promos")
    row("MAE semaines SANS promo",    mae_no_promo, "précision du modèle hors promo")

    print(f"\n  INTERPRÉTATION :")
    if not np.isnan(mae_promo) and mae_promo > mae_no_promo * 1.3:
        print("  ⚠️  Le modèle est moins précis pendant les promotions")
        print("       → normal si les données de promo sont peu nombreuses.")
    else:
        print("  ✅ La précision est homogène entre semaines promo et non-promo.")


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Évaluation des modèles ML Precios — split temporel 80/20"
    )
    parser.add_argument(
        "--model",
        choices=["demand", "anomaly", "price", "promo", "all"],
        default="all",
        help="Modèle à évaluer (défaut : all)"
    )
    args = parser.parse_args()

    print(f"\n{'█' * 60}")
    print(f"  ÉVALUATION DES MODÈLES ML — PRECIOS")
    print(f"  Data directory : {DATA_DIR}")
    print(f"{'█' * 60}")

    if not DATA_DIR.exists():
        print(f"\n  [ERREUR] Le dossier /data est introuvable : {DATA_DIR}")
        print("  Vérifie que le script est lancé depuis la racine du projet.")
        sys.exit(1)

    models = {
        "demand":  evaluate_demand,
        "anomaly": evaluate_anomaly,
        "price":   evaluate_price,
        "promo":   evaluate_promo,
    }

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
