import pandas as pd
import numpy as np
import joblib
import json
from pathlib import Path
from sklearn.metrics import precision_score, recall_score, f1_score

from services.ml_training_service.app.services.anomaly_detectors import build_anomaly_dataset

from ..core.config import DATA_DIR, MODELS_DIR, REPORTS_DIR

def _latest_file(folder: Path, prefix: str, suffix: str):
    files = sorted(folder.glob(f"{prefix}*{suffix}"))
    if not files:
        raise FileNotFoundError(f"Aucun fichier trouvé pour {prefix} dans {folder}")
    return files[-1]

def evaluate_anomaly_model() -> dict:
    products = pd.read_csv(DATA_DIR / "products.csv")
    competitor_prices = pd.read_csv(DATA_DIR / "competitor_prices.csv")

    df = build_anomaly_dataset(products, competitor_prices)

    # vérité approximative
    df["is_anomaly"] = (
        (df["status_bad"] == 1)
        | (np.abs(df["delta_pct"]) > 0.5)
        | (np.abs(df["log_ratio"]) > np.log(1.5))
    ).astype(int)

    y_true = df["is_anomaly"].values

    scaler_path = _latest_file(MODELS_DIR, "anomaly_scaler_", ".joblib")
    iforest_path = _latest_file(MODELS_DIR, "anomaly_iforest_", ".joblib")
    meta_path = _latest_file(REPORTS_DIR, "anomaly_ml_meta_", ".json")

    scaler = joblib.load(scaler_path)
    iforest = joblib.load(iforest_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    feature_cols = meta["feature_cols"]
    threshold = float(meta["score_threshold"])

    X = df[feature_cols].values.astype(float)
    Xs = scaler.transform(X)

    scores = iforest.decision_function(Xs)
    y_pred = (scores < threshold).astype(int)

    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)

    return {
        "dataset_size": int(len(df)),
        "anomalies_in_dataset": int(y_true.sum()),
        "metrics": {
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "f1_score": round(float(f1), 4)
        }
    }
    
#prix concurrent << coût
# variation énorme de prix
# status != OK

# !!!!!!!!!!!