"""
train.py  —  version améliorée
================================
Améliorations vs version originale :
1. Filtrage des produits ultra-sparses avant l'entraînement
2. Merge automatique des promotions (is_promo_active, promo_expected_lift, …)
3. Hyperparamètres XGBoost recalibrés (moins d'overfitting)
4. Lags et rolling stats étendus (60j, 90j) — fournis par utils.py
5. Walk-forward CV optionnel pour estimer les métriques plus robustement
6. Rapport JSON enrichi
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List

import joblib
import numpy as np
import pandas as pd

try:
    from xgboost import XGBRegressor
except Exception:
    XGBRegressor = None

from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from utils import (
    load_and_clean_data,
    feature_engineering,
    filter_sparse_products,    # ← nouveau
    merge_promotions,          # ← nouveau
    time_series_cv_splits,     # ← nouveau
)


BASE_DIR = Path(__file__).resolve().parent
LOCAL_MODELS_DIR = BASE_DIR / "models"
INFERENCE_MODELS_DIR = BASE_DIR / "services" / "inference_service" / "app" / "models"

# Chemin par défaut des promotions (même dossier que le CSV de training)
DEFAULT_PROMOTIONS_PATH = BASE_DIR / "data" / "promotions.csv"

BASE_FEATURES = [
    "price",
    "price_change",
    "price_lag_1",
    "day",
    "month",
    "day_of_week",
    "week_of_year",
    "is_weekend",
    "quarter",
    "is_month_start",
    "is_month_end",
    "is_quarter_start",
    "is_quarter_end",
    "month_sin",
    "month_cos",
    "dow_sin",
    "dow_cos",
    "lag_1",
    "lag_7",
    "lag_14",
    "lag_21",
    "lag_30",
    "lag_60",          # ← nouveau
    "lag_90",          # ← nouveau
    "rolling_mean_7",
    "rolling_mean_14",
    "rolling_mean_30",
    "rolling_mean_60",  # ← nouveau
    "rolling_mean_90",  # ← nouveau
    "rolling_std_7",
    "rolling_std_30",   # ← nouveau
    "rolling_max_7",
    "rolling_min_7",
    "sales_diff",
    "trend",
    "trend_short_medium",
    "trend_medium_long",
    "trend_long",       # ← nouveau
    "cumulative_sales",
]

OPTIONAL_NUMERIC_FEATURES = [
    "stock",
    "stock_lag",
    "stock_to_sales",
    "stock_vs_avg_sales",
    "discount",
    "competitor_pricing",
    "units_ordered",
    "price_discount_interaction",
    "price_vs_competitor",
    "competitor_ratio",
    "promo_discount_interaction",
    "is_promo_active",     
    "promo_discount",       
    "promo_expected_lift",  
    "is_promo_active_lag1", 
    "promo_expected_lift_lag1",  
    "price_x_promo",         
    "lift_x_discount",       
]

ONE_HOT_PREFIXES = [
    "category_",
    "region_",
    "weather_condition_",
    "holiday_promotion_",
    "seasonality_",
    "store_id_",
    "product_id_",
]



def _mape_safe(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = y_true != 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _wape_safe(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.sum(np.abs(y_true))
    if denom == 0:
        return 0.0
    return float(np.sum(np.abs(y_true - y_pred)) / denom * 100)


def _smape_safe(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    mask = denom != 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)


def _metrics(y_true, y_pred) -> Dict[str, float]:
    return {
        "MAE": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "RMSE": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "R2": round(float(r2_score(y_true, y_pred)), 4),
        "MAPE": round(_mape_safe(y_true, y_pred), 4),
        "WAPE": round(_wape_safe(y_true, y_pred), 4),
        "SMAPE": round(_smape_safe(y_true, y_pred), 4),
    }



EXCLUDE_COLS = {"product_id_original", "date", "sales", "target_7d"}

def _select_features(df: pd.DataFrame) -> List[str]:
    features = [
        col for col in BASE_FEATURES + OPTIONAL_NUMERIC_FEATURES
        if col in df.columns and col not in EXCLUDE_COLS
    ]
    encoded = [
        col for col in df.columns
        if any(col.startswith(prefix) for prefix in ONE_HOT_PREFIXES)
        and col not in EXCLUDE_COLS
    ]
    features += encoded
    return list(dict.fromkeys(features))



def _time_split(df: pd.DataFrame, test_ratio: float = 0.2):
    df = df.sort_values("date").copy()
    unique_dates = sorted(df["date"].unique())
    split_idx = int(len(unique_dates) * (1 - test_ratio))
    split_date = unique_dates[split_idx]
    train_df = df[df["date"] < split_date].copy()
    test_df = df[df["date"] >= split_date].copy()
    return train_df, test_df, pd.Timestamp(split_date)


# ─────────────────────────────────────────────
# Construction du modèle  (hyperparamètres recalibrés)
# ─────────────────────────────────────────────

def _build_model(model_type: str = "xgb"):
    if model_type == "xgb" and XGBRegressor is not None:
        return XGBRegressor(
            n_estimators=800,
            max_depth=4,           # ← réduit (5→4) pour moins d'overfitting
            learning_rate=0.03,    # ← réduit (0.035→0.03)
            subsample=0.80,        # ← réduit (0.85→0.80)
            colsample_bytree=0.70, # ← réduit (0.85→0.70)
            reg_alpha=0.30,        # ← augmenté (0.05→0.30)
            reg_lambda=2.0,        # ← augmenté (1.2→2.0)
            min_child_weight=5,    # ← augmenté (3→5)
            random_state=42,
            objective="reg:squarederror",
            early_stopping_rounds=50,   # ← nouveau : arrêt anticipé
        )

    if model_type == "rf":
        return RandomForestRegressor(
            n_estimators=400,
            max_depth=12,          # ← réduit (14→12)
            min_samples_leaf=4,    # ← augmenté (2→4)
            random_state=42,
            n_jobs=-1,
        )

    return HistGradientBoostingRegressor(
        max_iter=600,
        learning_rate=0.03,
        max_leaf_nodes=24,         # ← réduit (31→24)
        l2_regularization=0.2,    # ← augmenté (0.05→0.20)
        min_samples_leaf=30,       # ← nouveau
        random_state=42,
    )


# ─────────────────────────────────────────────
# Sauvegarde
# ─────────────────────────────────────────────

def _save_artifacts(model, features, use_log_transform: bool, report: dict, output_dirs: List[Path]):
    for out_dir in output_dirs:
        out_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, out_dir / "demand_model.pkl")
        joblib.dump(features, out_dir / "demand_features.pkl")
        joblib.dump(use_log_transform, out_dir / "use_log_transform.pkl")
        with open(out_dir / "demand_training_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# Entraînement principal
# ─────────────────────────────────────────────

def train_demand_model(
    path: str = "train_data.csv",
    promotions_path: str | None = None,
    model_type: str = "xgb",
    use_log_transform: bool = True,
    test_ratio: float = 0.2,
    max_zero_rate: float = 0.70,   # ← nouveau : seuil de filtrage sparse
    run_cv: bool = False,          # ← nouveau : activer le walk-forward CV
    n_cv_splits: int = 4,
) -> dict:

    # 1. Chargement
    df_raw = load_and_clean_data(path)

    # 2. Merge promotions  ← NOUVEAU
    if promotions_path is None:
        candidate = Path(path).parent / "promotions.csv"
        promotions_path = str(candidate) if candidate.exists() else str(DEFAULT_PROMOTIONS_PATH)
    df_raw = merge_promotions(df_raw, promotions_path)

    # 3. Filtrage produits sparses  ← NOUVEAU
    df_raw = filter_sparse_products(df_raw, max_zero_rate=max_zero_rate)

    # 4. Feature engineering
    df = feature_engineering(df_raw, drop_leaky_columns=True)
    df = df.sort_values("date").reset_index(drop=True)

    features = _select_features(df)
    if not features:
        raise ValueError("Aucune feature disponible pour l'entraînement.")

    target_col = "target_7d" if "target_7d" in df.columns else "sales"

    # 5. Walk-forward CV (optionnel)  ← NOUVEAU
    cv_results = []
    if run_cv:
        print(f"[CV] Démarrage walk-forward CV ({n_cv_splits} folds)…")
        for fold_i, (train_cv, test_cv) in enumerate(
            time_series_cv_splits(df, n_splits=n_cv_splits, test_ratio_per_fold=0.10)
        ):
            X_tr = train_cv[features].astype(float)
            y_tr_raw = train_cv[target_col].astype(float).clip(lower=0)
            X_te = test_cv[features].astype(float)
            y_te = test_cv[target_col].astype(float).clip(lower=0)

            y_tr = np.log1p(y_tr_raw) if use_log_transform else y_tr_raw
            m_cv = _build_model(model_type=model_type)

            if model_type == "xgb" and XGBRegressor is not None:
                X_val = X_te  # utilise le test comme validation pour early stopping
                y_val = np.log1p(y_te) if use_log_transform else y_te
                m_cv.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
            else:
                m_cv.fit(X_tr, y_tr)

            pred_raw = m_cv.predict(X_te)
            pred = np.maximum(0, np.expm1(pred_raw) if use_log_transform else pred_raw)
            fold_metrics = _metrics(y_te.values, pred)
            fold_metrics["fold"] = fold_i + 1
            cv_results.append(fold_metrics)
            print(f"  Fold {fold_i+1} — R²={fold_metrics['R2']:.3f} | "
                  f"WAPE={fold_metrics['WAPE']:.1f}% | MAPE={fold_metrics['MAPE']:.1f}%")

        mean_cv = {
            k: round(float(np.mean([f[k] for f in cv_results])), 4)
            for k in ["MAE", "RMSE", "R2", "MAPE", "WAPE", "SMAPE"]
        }
        print(f"[CV] Moyenne : R²={mean_cv['R2']:.3f} | WAPE={mean_cv['WAPE']:.1f}%")

    # 6. Entraînement final sur tout le dataset (split temporel classique)
    train_df, test_df, split_date = _time_split(df, test_ratio=test_ratio)
    if train_df.empty or test_df.empty:
        raise ValueError("Split temporel impossible : train ou test vide.")

    X_train = train_df[features].astype(float)
    X_test = test_df[features].astype(float)
    y_train_raw = train_df[target_col].astype(float).clip(lower=0)
    y_test = test_df[target_col].astype(float).clip(lower=0)

    y_train = np.log1p(y_train_raw) if use_log_transform else y_train_raw

    model = _build_model(model_type=model_type)

    # Early stopping sur XGBoost avec 10% du train comme validation interne
    if model_type == "xgb" and XGBRegressor is not None:
        val_size = int(len(X_train) * 0.10)
        X_val_int = X_train.iloc[-val_size:]
        y_val_int = y_train.iloc[-val_size:]
        X_train_fit = X_train.iloc[:-val_size]
        y_train_fit = y_train.iloc[:-val_size]
        model.fit(
            X_train_fit, y_train_fit,
            eval_set=[(X_val_int, y_val_int)],
            verbose=False,
        )
    else:
        model.fit(X_train, y_train)

    train_pred_raw = model.predict(X_train)
    test_pred_raw = model.predict(X_test)

    train_pred = np.maximum(0, np.expm1(train_pred_raw) if use_log_transform else train_pred_raw)
    test_pred = np.maximum(0, np.expm1(test_pred_raw) if use_log_transform else test_pred_raw)

    # 7. Rapport
    report = {
        "status": "training_completed",
        "data_path": str(path),
        "promotions_path": str(promotions_path),
        "model_type": (
            model_type
            if not (model_type == "xgb" and XGBRegressor is None)
            else "hist_gradient_boosting_fallback"
        ),
        "use_log_transform": use_log_transform,
        "max_zero_rate_filter": max_zero_rate,
        "rows_raw": int(len(df_raw)),
        "rows_after_features": int(len(df)),
        "rows_train": int(len(train_df)),
        "rows_test": int(len(test_df)),
        "split_date": str(split_date.date()),
        "features_count": len(features),
        "features_used": features,
        "target_col": target_col,
        "target_mean_train": round(float(y_train_raw.mean()), 4),
        "target_mean_test": round(float(y_test.mean()), 4),
        "train_metrics": _metrics(y_train_raw.values, train_pred),
        "test_metrics": _metrics(y_test.values, test_pred),
        "cv_folds": cv_results if run_cv else [],
        "cv_mean_metrics": mean_cv if run_cv else {},
    }

    output_dirs = [LOCAL_MODELS_DIR]
    if INFERENCE_MODELS_DIR.exists() or (BASE_DIR / "services" / "inference_service").exists():
        output_dirs.append(INFERENCE_MODELS_DIR)

    _save_artifacts(model, features, use_log_transform, report, output_dirs)
    return report


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Training amélioré du modèle de demande")
    parser.add_argument("--data", default="train_data.csv", help="Chemin CSV de training")
    parser.add_argument("--promotions", default=None, help="Chemin promotions.csv (optionnel)")
    parser.add_argument("--model", default="xgb", choices=["xgb", "hgb", "rf"])
    parser.add_argument("--no-log", action="store_true", help="Désactiver log1p/expm1")
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument(
        "--max-zero-rate", type=float, default=0.70,
        help="Taux max de zéros par produit (défaut 0.70). "
             "Produits au-dessus sont exclus du training.",
    )
    parser.add_argument("--cv", action="store_true", help="Activer le walk-forward CV")
    parser.add_argument("--cv-splits", type=int, default=4, help="Nombre de folds CV")
    args = parser.parse_args()

    result = train_demand_model(
        path=args.data,
        promotions_path=args.promotions,
        model_type=args.model,
        use_log_transform=not args.no_log,
        test_ratio=args.test_ratio,
        max_zero_rate=args.max_zero_rate,
        run_cv=args.cv,
        n_cv_splits=args.cv_splits,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
