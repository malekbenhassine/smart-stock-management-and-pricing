import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .demand_ml_trainer import (
    build_weekly_sales,
    make_supervised_features,
    train_quantile_gbr,
)


def mean_absolute_percentage_error_safe(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    MAPE sécurisé : ignore les valeurs y_true = 0 pour éviter division par zéro.
    Retourne un pourcentage.
    """
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)

    mask = y_true != 0
    if mask.sum() == 0:
        return 0.0

    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)


def train_test_split_time(df: pd.DataFrame, test_ratio: float = 0.2) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split temporel global :
    - anciennes semaines -> train
    - dernières semaines -> test
    """
    weeks = sorted(df["week"].unique())
    split_idx = int(len(weeks) * (1 - test_ratio))

    train_weeks = weeks[:split_idx]
    test_weeks = weeks[split_idx:]

    train_df = df[df["week"].isin(train_weeks)].copy()
    test_df = df[df["week"].isin(test_weeks)].copy()

    return train_df, test_df


def evaluate_demand_model(sales: pd.DataFrame) -> Dict[str, Any]:
    """
    Évalue le modèle de demande hebdomadaire quantile.
    """
    weekly = build_weekly_sales(sales)
    supervised, feature_cols = make_supervised_features(weekly, lags=4)

    if supervised.empty:
        raise ValueError("Le dataset supervisé est vide. Vérifie les données de ventes.")

    train_df, test_df = train_test_split_time(supervised, test_ratio=0.2)

    if train_df.empty or test_df.empty:
        raise ValueError("Train ou test vide. Impossible d'évaluer le modèle.")

    X_train = train_df[feature_cols].values.astype(float)
    y_train = train_df["qty"].values.astype(float)

    X_test = test_df[feature_cols].values.astype(float)
    y_test = test_df["qty"].values.astype(float)

    # Entraînement quantiles
    model_p10 = train_quantile_gbr(X_train, y_train, alpha=0.10)
    model_p50 = train_quantile_gbr(X_train, y_train, alpha=0.50)
    model_p90 = train_quantile_gbr(X_train, y_train, alpha=0.90)

    # Prédictions
    y_pred_p10 = np.maximum(0.0, model_p10.predict(X_test))
    y_pred_p50 = np.maximum(0.0, model_p50.predict(X_test))
    y_pred_p90 = np.maximum(0.0, model_p90.predict(X_test))

    # Métriques principales sur p50
    mae = float(mean_absolute_error(y_test, y_pred_p50))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_p50)))
    mape = float(mean_absolute_percentage_error_safe(y_test, y_pred_p50))

    # Couverture de l’intervalle [p10, p90]
    inside_interval = ((y_test >= y_pred_p10) & (y_test <= y_pred_p90)).astype(int)
    coverage_10_90 = float(inside_interval.mean() * 100.0)

    # Largeur moyenne de l’intervalle
    interval_width_mean = float(np.mean(y_pred_p90 - y_pred_p10))

    # Quelques stats utiles
    results = {
        "dataset": {
            "weekly_rows": int(len(weekly)),
            "supervised_rows": int(len(supervised)),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
            "n_products": int(supervised["product_id"].nunique()),
        },
        "metrics": {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape_percent": round(mape, 4),
            "coverage_10_90_percent": round(coverage_10_90, 4),
            "mean_interval_width": round(interval_width_mean, 4),
        },
        "explanation": {
            "mae": "Erreur absolue moyenne en unités vendues.",
            "rmse": "Erreur quadratique moyenne, pénalise davantage les grosses erreurs.",
            "mape_percent": "Erreur moyenne en pourcentage.",
            "coverage_10_90_percent": "Pourcentage de vraies valeurs couvertes par l’intervalle [p10, p90].",
            "mean_interval_width": "Largeur moyenne de l’intervalle de confiance prédit.",
        }
    }

    return results