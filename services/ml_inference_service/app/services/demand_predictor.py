import numpy as np
import pandas as pd
from typing import Dict, Any
from pathlib import Path
from .model_store import ModelStore


def explain_demand_weekly(p10: float, p50: float, p90: float) -> str:
    return (
        f"La demande hebdomadaire attendue pour ce produit est estimée à environ {p50:.0f} unités. "
        f"Dans une hypothèse prudente, elle pourrait se situer autour de {p10:.0f} unités, "
        f"tandis que dans une hypothèse plus soutenue, elle pourrait atteindre {p90:.0f} unités. "
        f"Cette prévision permet d’anticiper les besoins de stock et d’ajuster plus finement les décisions de réapprovisionnement."
    )


def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    df = sales.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time

    weekly = df.groupby(["product_id", "week"], as_index=False).agg(
        qty=("qty", "sum"),
        price_week=("unit_price", "mean"),
    )

    return weekly.sort_values(["product_id", "week"])


class DemandPredictor:
    def __init__(self, data_dir: Path, models_dir: Path):
        self.data_dir = data_dir
        self.store = ModelStore(models_dir)

    def predict_weekly(self, product_id: int) -> Dict[str, Any]:
        sales = pd.read_csv(self.data_dir / "sales.csv")
        weekly = build_weekly_sales(sales)

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

            last_week = pd.to_datetime(g["week"].iloc[-1])
            next_week = last_week + pd.Timedelta(days=7)
            weekofyear = int(next_week.isocalendar().week)

            price_week = float(g["price_week"].iloc[-1])

            X = np.array([[
                float(product_id),
                price_week,
                float(weekofyear),
                lag_1,
                lag_2,
                lag_3,
                lag_4,
                roll_mean_4,
                roll_std_4
            ]], dtype=float)

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
                "explanation": (
                    f"La prévision est issue d’un calcul de secours basé sur l’historique disponible "
                    f"sur {stats['history_weeks']} semaines. "
                    f"La demande hebdomadaire estimée reste centrée autour de {float(stats['p50']):.0f} unités, "
                    f"avec une variation possible entre {float(stats['p10']):.0f} et {float(stats['p90']):.0f} unités. "
                    f"Cette estimation est utile pour disposer d’un repère opérationnel même en l’absence d’un modèle plus avancé."
                ),
                "source": "BASELINE",
            }