"""
utils.py  —  version améliorée
================================
Améliorations vs version originale :
1. Merge automatique des promotions (expected_lift, is_promo_active, promo_discount)
2. Lags plus longs : 60 et 90 jours
3. Rolling stats 60 et 90 jours
4. Helper walk-forward CV (time_series_cv_splits)
5. Helper de filtrage des produits ultra-sparses (filter_sparse_products)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


COLUMN_MAPPING = {
    "date": ["date", "datetime", "day", "jour", "fecha", "timestamp"],
    "sales": ["sales", "sale", "demand", "quantity", "qty", "ventes", "vente", "demandes", "units_sold"],
    "price": ["price", "prix", "unit_price", "selling_price", "montant", "current_price"],
    "stock": ["stock", "inventory", "inventaire", "available_stock", "qte_stock", "inventory_level"],
    "store_id": ["store_id", "store", "shop_id", "magasin_id"],
    "product_id": ["product_id", "product", "item_id", "produit_id", "sku"],
    "category": ["category", "categorie", "product_category"],
    "region": ["region", "zone", "area"],
    "units_ordered": ["units_ordered", "ordered_units", "quantity_ordered", "orders"],
    "demand_forecast": ["demand_forecast", "forecast", "sales_forecast", "prevision_demande"],
    "discount": ["discount", "remise", "promo_discount", "discount_percent"],
    "weather_condition": ["weather_condition", "weather", "meteo", "climate"],
    "holiday_promotion": ["holiday/promotion", "holiday_promotion", "promotion", "holiday", "is_holiday"],
    "competitor_pricing": ["competitor_pricing", "competitor_price", "prix_concurrent", "comp_median"],
    "seasonality": ["seasonality", "season", "saison"],
}

NUMERIC_COLUMNS = [
    "sales", "price", "stock", "units_ordered",
    "discount", "competitor_pricing", "demand_forecast",
]

CATEGORICAL_COLUMNS = [
    "category", "region", "weather_condition",
    "holiday_promotion", "seasonality", "store_id", "product_id",
]


# ─────────────────────────────────────────────
# Chargement & nettoyage
# ─────────────────────────────────────────────

def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
        .str.replace("-", "_", regex=False)
    )
    rename_dict = {}
    for standard_name, aliases in COLUMN_MAPPING.items():
        for col in df.columns:
            if col in aliases:
                rename_dict[col] = standard_name
                break
    return df.rename(columns=rename_dict)


def load_and_clean_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = standardize_columns(df)

    if "product_id_original" in df.columns:
        df["product_id"] = df["product_id_original"].astype(str)

    required_columns = ["date", "sales", "price"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            f"Colonnes obligatoires manquantes : {missing_columns}. "
            f"Colonnes trouvées : {list(df.columns)}"
        )

    defaults = {
        "store_id": "STORE_1",
        "product_id": "PRODUCT_1",
        "category": "UNKNOWN",
        "region": "UNKNOWN",
        "weather_condition": "Unknown",
        "holiday_promotion": 0,
        "seasonality": "Unknown",
        "stock": 0,
        "units_ordered": 0,
        "discount": 0,
        "competitor_pricing": np.nan,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    df = df.drop_duplicates().copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["sales", "price"]).copy()
    df["sales"] = df["sales"].clip(lower=0)
    df["price"] = df["price"].clip(lower=0)
    df["discount"] = df["discount"].fillna(0).clip(lower=0)
    df["stock"] = df["stock"].fillna(0).clip(lower=0)
    df["units_ordered"] = df["units_ordered"].fillna(0).clip(lower=0)
    df["competitor_pricing"] = df["competitor_pricing"].fillna(df["price"])

    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# NOUVEAU : filtrage produits sparses
# ─────────────────────────────────────────────

def filter_sparse_products(df: pd.DataFrame, max_zero_rate: float = 0.70) -> pd.DataFrame:
    """
    Supprime les produits dont le taux de zéros dépasse max_zero_rate.

    Avec tes données :
      - produit 12 → 92% de zéros  → supprimé
      - produit 23 → 85% de zéros  → supprimé
      - produit 29 → 65% de zéros  → supprimé au seuil 0.70 ?  non (0.65 < 0.70)
    Ajuste max_zero_rate selon ton besoin.
    """
    zero_rates = df.groupby("product_id")["sales"].transform(
        lambda s: (s == 0).mean()
    )
    before = len(df)
    df = df[zero_rates <= max_zero_rate].copy()
    removed = before - len(df)
    if removed:
        print(f"[filter_sparse_products] {removed} lignes supprimées "
              f"(taux de zéros > {max_zero_rate:.0%})")
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# NOUVEAU : merge promotions
# ─────────────────────────────────────────────

def merge_promotions(df: pd.DataFrame, promotions_path: str) -> pd.DataFrame:
    """
    Joint promotions.csv sur (product_id, date).

    Colonnes ajoutées :
      - is_promo_active   : 1 si une promo est en cours ce jour
      - promo_discount    : discount_percent de la promo (0 si aucune)
      - promo_expected_lift : expected_lift de la promo (1.0 si aucune)

    Le fichier promotions.csv doit avoir :
      product_id, start_date, end_date, discount_percent, expected_lift
    """
    try:
        promo = pd.read_csv(promotions_path)
    except FileNotFoundError:
        print(f"[merge_promotions] Fichier introuvable : {promotions_path} — étape ignorée.")
        return df

    promo["start_date"] = pd.to_datetime(promo["start_date"], errors="coerce")
    promo["end_date"] = pd.to_datetime(promo["end_date"], errors="coerce")
    promo = promo.dropna(subset=["start_date", "end_date"]).copy()

    # Expansion de chaque promo en une ligne par jour
    rows = []
    for _, row in promo.iterrows():
        dates = pd.date_range(row["start_date"], row["end_date"], freq="D")
        for d in dates:
            rows.append({
                "product_id": row["product_id"],
                "date": d,
                "promo_discount": row.get("discount_percent", 0),
                "promo_expected_lift": row.get("expected_lift", 1.0),
            })

    if not rows:
        print("[merge_promotions] Aucune ligne de promo générée.")
        return df

    promo_daily = pd.DataFrame(rows)

    # Si plusieurs promos se chevauchent le même jour → on prend la plus forte
    promo_daily = (
        promo_daily
        .groupby(["product_id", "date"], as_index=False)
        .agg(
            promo_discount=("promo_discount", "max"),
            promo_expected_lift=("promo_expected_lift", "max"),
        )
    )
    promo_daily["is_promo_active"] = 1

    # Harmoniser le type de product_id avant le merge
    df = df.copy()
    promo_daily["product_id"] = promo_daily["product_id"].astype(df["product_id"].dtype)

    df = df.merge(promo_daily, on=["product_id", "date"], how="left")
    df["is_promo_active"] = df["is_promo_active"].fillna(0).astype(int)
    df["promo_discount"] = df["promo_discount"].fillna(0)
    df["promo_expected_lift"] = df["promo_expected_lift"].fillna(1.0)

    n_promo_days = df["is_promo_active"].sum()
    print(f"[merge_promotions] {n_promo_days} jours-produit avec promo active jointe.")
    return df


# ─────────────────────────────────────────────
# Feature engineering (étendu)
# ─────────────────────────────────────────────

def _group_columns(df: pd.DataFrame) -> list[str]:
    group_cols = []
    if "store_id" in df.columns:
        group_cols.append("store_id")
    if "product_id" in df.columns:
        group_cols.append("product_id")
    return group_cols


def _safe_div(num, den, default=0.0):
    out = num / den.replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan).fillna(default)


def feature_engineering(df: pd.DataFrame, drop_leaky_columns: bool = True) -> pd.DataFrame:
    """
    Construit les features d'entraînement.

    Nouveautés vs version originale :
    - Lags 60 et 90 jours
    - Rolling mean/std 60 et 90 jours
    - Features promotions (is_promo_active, promo_discount, promo_expected_lift)
      si elles ont été ajoutées par merge_promotions()
    """
    df = df.copy()

    if drop_leaky_columns and "demand_forecast" in df.columns:
        df = df.drop(columns=["demand_forecast"])

    group_cols = _group_columns(df)
    sort_cols = group_cols + ["date"] if group_cols else ["date"]
    df = df.sort_values(sort_cols).reset_index(drop=True)

    # ── Features temporelles ──────────────────────────────────────────────────
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

    # ── Features historiques (sans fuite de données) ─────────────────────────
    if group_cols:
        g = df.groupby(group_cols, group_keys=False)

        for lag in [1, 7, 14, 21, 30, 60, 90]:          # ← 60 et 90 nouveaux
            df[f"lag_{lag}"] = g["sales"].shift(lag)

        df["price_lag_1"] = g["price"].shift(1)
        df["price_change"] = g["price"].pct_change()

        if "stock" in df.columns:
            df["stock_lag"] = g["stock"].shift(1)

        for w, mp in [(7, 3), (14, 5), (30, 7), (60, 14), (90, 21)]:   # ← 60, 90 nouveaux
            df[f"rolling_mean_{w}"] = g["sales"].transform(
                lambda s, _w=w, _mp=mp: s.shift(1).rolling(_w, min_periods=_mp).mean()
            )

        df["rolling_std_7"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(7, min_periods=3).std()
        )
        df["rolling_std_30"] = g["sales"].transform(      # ← nouveau
            lambda s: s.shift(1).rolling(30, min_periods=7).std()
        )
        df["rolling_max_7"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(7, min_periods=3).max()
        )
        df["rolling_min_7"] = g["sales"].transform(
            lambda s: s.shift(1).rolling(7, min_periods=3).min()
        )
        df["sales_diff"] = g["sales"].transform(lambda s: s.shift(1).diff())
        df["cumulative_sales"] = g["sales"].transform(lambda s: s.shift(1).cumsum())

    else:
        for lag in [1, 7, 14, 21, 30, 60, 90]:
            df[f"lag_{lag}"] = df["sales"].shift(lag)
        df["price_lag_1"] = df["price"].shift(1)
        df["price_change"] = df["price"].pct_change()
        df["stock_lag"] = df["stock"].shift(1) if "stock" in df.columns else np.nan
        for w, mp in [(7, 3), (14, 5), (30, 7), (60, 14), (90, 21)]:
            df[f"rolling_mean_{w}"] = df["sales"].shift(1).rolling(w, min_periods=mp).mean()
        df["rolling_std_7"] = df["sales"].shift(1).rolling(7, min_periods=3).std()
        df["rolling_std_30"] = df["sales"].shift(1).rolling(30, min_periods=7).std()
        df["rolling_max_7"] = df["sales"].shift(1).rolling(7, min_periods=3).max()
        df["rolling_min_7"] = df["sales"].shift(1).rolling(7, min_periods=3).min()
        df["sales_diff"] = df["sales"].shift(1).diff()
        df["cumulative_sales"] = df["sales"].shift(1).cumsum()

    # ── Features dérivées ────────────────────────────────────────────────────
    df["trend"] = df["rolling_mean_7"] - df["rolling_mean_30"]
    df["trend_short_medium"] = df["rolling_mean_7"] - df["rolling_mean_14"]
    df["trend_medium_long"] = df["rolling_mean_14"] - df["rolling_mean_30"]
    df["trend_long"] = df["rolling_mean_30"] - df["rolling_mean_90"]   # ← nouveau

    if "stock" in df.columns:
        df["stock_to_sales"] = _safe_div(
            df["stock_lag"].fillna(df["stock"]),
            df["lag_1"].fillna(0) + 1,
            default=0.0,
        )
        df["stock_vs_avg_sales"] = _safe_div(
            df["stock_lag"].fillna(df["stock"]),
            df["rolling_mean_7"].fillna(0) + 1,
            default=0.0,
        )

    if "discount" in df.columns:
        df["price_discount_interaction"] = df["price"] * df["discount"].fillna(0)

    if "competitor_pricing" in df.columns:
        df["price_vs_competitor"] = df["price"] - df["competitor_pricing"]
        df["competitor_ratio"] = _safe_div(
            df["price"], df["competitor_pricing"] + 1, default=1.0
        )

    if "discount" in df.columns and "holiday_promotion" in df.columns:
        holiday_numeric = pd.to_numeric(df["holiday_promotion"], errors="coerce").fillna(0)
        df["promo_discount_interaction"] = holiday_numeric * df["discount"].fillna(0)

    # ── NOUVEAU : features promotions ─────────────────────────────────────────
    if "is_promo_active" in df.columns:
        # lag de la promo (le modèle voit si hier il y avait une promo)
        if group_cols:
            g2 = df.groupby(group_cols, group_keys=False)
            df["is_promo_active_lag1"] = g2["is_promo_active"].shift(1).fillna(0)
            df["promo_expected_lift_lag1"] = g2["promo_expected_lift"].shift(1).fillna(1.0)
        else:
            df["is_promo_active_lag1"] = df["is_promo_active"].shift(1).fillna(0)
            df["promo_expected_lift_lag1"] = df["promo_expected_lift"].shift(1).fillna(1.0)

        # interaction prix × promo
        df["price_x_promo"] = df["price"] * df["is_promo_active"]
        df["lift_x_discount"] = df["promo_expected_lift"] * df["promo_discount"].fillna(0)

    # ── Cible métier : demande sur les 7 prochains jours ────────────────────
    def _future_sum_7(s: pd.Series) -> pd.Series:
        return (
            s.iloc[::-1]
            .shift(1)
            .rolling(7, min_periods=1)
            .sum()
            .iloc[::-1]
        )

    if group_cols:
        df["target_7d"] = df.groupby(group_cols, group_keys=False)["sales"].transform(
            _future_sum_7
        )
    else:
        df["target_7d"] = _future_sum_7(df["sales"])

    # ── Encodage catégoriel ──────────────────────────────────────────────────
    existing_cat = [c for c in CATEGORICAL_COLUMNS if c in df.columns]
    for col in existing_cat:
        df[col] = df[col].astype(str)
    if existing_cat:
        df = pd.get_dummies(df, columns=existing_cat, drop_first=False)

    # Nettoyage final
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna().reset_index(drop=True)

    return df


# ─────────────────────────────────────────────
# NOUVEAU : walk-forward cross-validation
# ─────────────────────────────────────────────

def time_series_cv_splits(
    df: pd.DataFrame,
    n_splits: int = 4,
    test_ratio_per_fold: float = 0.10,
):
    """
    Génère n_splits folds glissants pour un CV temporel.

    Chaque fold :
      - train = tout ce qui précède la fenêtre test
      - test  = fenêtre glissante d'environ test_ratio_per_fold dates

    Utilisation dans train.py :
        from utils import time_series_cv_splits
        for fold_i, (train_df, test_df) in enumerate(time_series_cv_splits(df)):
            ...
    """
    df = df.sort_values("date")
    unique_dates = sorted(df["date"].unique())
    n_dates = len(unique_dates)
    fold_size = int(n_dates * test_ratio_per_fold)

    for i in range(n_splits):
        test_end_idx = n_dates - i * fold_size
        test_start_idx = test_end_idx - fold_size
        if test_start_idx <= fold_size:
            break
        train_dates = unique_dates[:test_start_idx]
        test_dates = unique_dates[test_start_idx:test_end_idx]
        yield (
            df[df["date"].isin(train_dates)].copy(),
            df[df["date"].isin(test_dates)].copy(),
        )
