from pathlib import Path
import json
import numpy as np
import pandas as pd

def _latest_json(reports_dir: Path, prefix: str) -> Path:
    files = sorted(reports_dir.glob(f"{prefix}*.json"))
    if not files:
        raise FileNotFoundError(f"Aucun meta trouvé: {prefix} dans {reports_dir}")
    return files[-1]

class AnomalyMLEngine:
    """
    Détection anomalies ML non-supervisée:
    - StandardScaler + IsolationForest
    - score + explication via features dominantes (z-score)
    """
    def __init__(self, store, reports_dir: Path):
        self.store = store
        self.reports_dir = reports_dir

    def _prepare_features(self, product: dict, competitor_prices: pd.DataFrame) -> pd.DataFrame:
        pid = int(product["product_id"])
        cur = float(product["current_price"])

        df = competitor_prices[competitor_prices["product_id"] == pid].copy()
        if df.empty:
            return df

        df["collected_at"] = pd.to_datetime(df["collected_at"])
        df = df.sort_values(["competitor_id", "collected_at"])

        df["status_bad"] = (df["status"] != "OK").astype(int)
        df["ratio"] = df["competitor_price"] / max(cur, 1e-6)
        df["log_ratio"] = np.log(np.clip(df["ratio"], 1e-6, 1e6))

        # delta vs précédent (par competitor)
        df["prev_price"] = df.groupby("competitor_id")["competitor_price"].shift(1)
        df["delta_pct"] = (df["competitor_price"] - df["prev_price"]) / df["prev_price"]
        df["delta_pct"] = df["delta_pct"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        # gap heures
        df["prev_time"] = df.groupby("competitor_id")["collected_at"].shift(1)
        df["gap_hours"] = (df["collected_at"] - df["prev_time"]).dt.total_seconds() / 3600.0
        df["gap_hours"] = df["gap_hours"].fillna(df["gap_hours"].median() if df["gap_hours"].notna().any() else 0.0)

        return df
    
    def _explain_feature(self, feat: str) -> str:
        mapping = {
        "gap_hours": "La dernière collecte est trop ancienne / irrégulière (scraping instable ou retard).",
        "log_ratio": "Le ratio prix concurrent / prix interne est atypique (prix trop haut/bas ou mauvais matching).",
        "delta_pct": "Variation du prix concurrent très brusque par rapport à l’historique (choc ou donnée incohérente).",
        "status_bad": "Le scraping a retourné un statut non OK (donnée potentiellement invalide).",
        }
        return mapping.get(feat, f"Feature atypique: {feat}.")
    
    def detect_for_product_ml(self, product: dict, competitor_prices: pd.DataFrame) -> dict:
        scaler = self.store.load_latest("anomaly_scaler", "anomaly_scaler_")
        iforest = self.store.load_latest("anomaly_iforest", "anomaly_iforest_")

        meta_path = _latest_json(self.reports_dir, "anomaly_ml_meta_")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        feature_cols = meta["feature_cols"]
        threshold = float(meta["score_threshold"])
        feat_mean = np.array(meta["feature_mean"], dtype=float)
        feat_std = np.array(meta["feature_std"], dtype=float)

        df = self._prepare_features(product, competitor_prices)
        if df.empty:
            return {"product_id": int(product["product_id"]), "anomalies": []}

        # prendre la dernière observation par concurrent (c’est ce que tu affiches dans ta UI)
        latest = df.groupby("competitor_id", as_index=False).tail(1).copy()

        X = latest[feature_cols].values.astype(float)
        Xs = scaler.transform(X)
        scores = iforest.decision_function(Xs)  # plus grand => normal
        latest["score"] = scores

        anomalies = []
        for row in latest.itertuples(index=False):
            if float(row.score) < threshold:
                x = np.array([getattr(row, c) for c in feature_cols], dtype=float)
                z = np.abs((x - feat_mean) / (feat_std + 1e-9))
                top_idx = int(np.argmax(z))
                top_feat = feature_cols[top_idx]
                reason = self._explain_feature(top_feat)
                anomalies.append({
                    "type": "ML_ANOMALY",
                    "severity": "HIGH" if float(row.score) < threshold - 0.05 else "MEDIUM",
                    "detail": f"Anomalie ML détectée (score={float(row.score):.3f}). {reason}"
                })

        return {"product_id": int(product["product_id"]), "anomalies": anomalies}
