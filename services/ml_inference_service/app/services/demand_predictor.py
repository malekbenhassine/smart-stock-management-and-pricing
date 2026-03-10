import numpy as np
import pandas as pd
from typing import Dict, Any
from pathlib import Path

from .model_store import ModelStore
from .preprocess import build_weekly_sales
from .explanations import explain_demand_weekly


class DemandPredictor:
    def __init__(self, data_dir: Path, models_dir: Path):
        self.data_dir = data_dir
        self.store = ModelStore(models_dir)

    def predict_weekly(self, product_id: int) -> Dict[str, Any]:
        # 1) Load data
        sales = pd.read_csv(self.data_dir / "sales.csv")
        weekly = build_weekly_sales(sales)

        # 2) Try ML quantile models
        try:
            m10 = self.store.load_latest("demand_ml_p10", "demand_ml_p10_")
            m50 = self.store.load_latest("demand_ml_p50", "demand_ml_p50_")
            m90 = self.store.load_latest("demand_ml_p90", "demand_ml_p90_")

            g = weekly[weekly["product_id"] == product_id].sort_values("week")
            y = g["qty"].values.astype(float)

            if len(y) < 4:
                raise ValueError("Historique insuffisant (<4 semaines) pour ML.")

            lag_1, lag_2, lag_3, lag_4 = y[-1], y[-2], y[-3], y[-4]
            roll_mean_4 = float(np.mean([lag_1, lag_2, lag_3, lag_4]))
            roll_std_4 = float(np.std([lag_1, lag_2, lag_3, lag_4]))

            X = np.array([[float(product_id), lag_1, lag_2, lag_3, lag_4, roll_mean_4, roll_std_4]], dtype=float)

            p10 = float(max(0.0, m10.predict(X)[0]))
            p50 = float(max(0.0, m50.predict(X)[0]))
            p90 = float(max(0.0, m90.predict(X)[0]))

            return {
                "product_id": product_id,
                "p10": p10,
                "p50": p50,
                "p90": p90,
                "explanation": explain_demand_weekly(p10, p50, p90),
                "source": "ML_QUANTILE_GBR",
            }

        except Exception:
            # 3) Fallback baseline (si dispo)
            demand_model = self.store.load_latest("demand", "demand_weekly_")
            stats = demand_model.per_product.get(product_id)

            if not stats:
                return {
                    "product_id": product_id,
                    "p10": 0.0,
                    "p50": 0.0,
                    "p90": 0.0,
                    "explanation": "Aucun historique suffisant pour fournir une prévision.",
                    "source": "NO_DATA",
                }

            return {
                "product_id": product_id,
                "p10": float(stats["p10"]),
                "p50": float(stats["p50"]),
                "p90": float(stats["p90"]),
                "explanation": f"Prévision de secours (baseline) basée sur l'historique (history_weeks={stats['history_weeks']}).",
                "source": "BASELINE",
            }