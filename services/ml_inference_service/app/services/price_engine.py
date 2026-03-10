from pathlib import Path
import json
import numpy as np
import pandas as pd
from datetime import datetime

def _latest_json(reports_dir: Path, prefix: str) -> Path:
    files = sorted(reports_dir.glob(f"{prefix}*.json"))
    if not files:
        raise FileNotFoundError(f"Aucun meta trouvé: {prefix} dans {reports_dir}")
    return files[-1]

class PriceMLRecommender:
    """
    ML prescriptive:
    - modèle ML: qty_week = f(price, concurrence, promo, lags, season)
    - recommandation: simuler des prix candidats et choisir celui qui maximise profit
    """
    def __init__(self, store, reports_dir: Path):
        self.store = store
        self.reports_dir = reports_dir

    def _build_weekly(self, sales: pd.DataFrame) -> pd.DataFrame:
        df = sales.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["week"] = df["timestamp"].dt.to_period("W").dt.start_time
        g = df.groupby(["product_id", "week"], as_index=False).agg(
            qty_week=("qty", "sum"),
            avg_price=("unit_price", "mean")
        )
        return g.sort_values(["product_id", "week"])

    def _competitor_week_median(self, competitor_prices: pd.DataFrame) -> pd.DataFrame:
        df = competitor_prices.copy()
        df["collected_at"] = pd.to_datetime(df["collected_at"])
        df["week"] = df["collected_at"].dt.to_period("W").dt.start_time
        med = df.groupby(["product_id", "week"], as_index=False)["competitor_price"].median()
        med = med.rename(columns={"competitor_price": "comp_median"})
        return med

    def _promo_flag_week(self, promotions: pd.DataFrame) -> pd.DataFrame:
        df = promotions.copy()
        df["start_date"] = pd.to_datetime(df["start_date"])
        df["end_date"] = pd.to_datetime(df["end_date"])
        # on crée une table (product_id, week) -> promo_flag=1 si promo active
        rows = []
        for r in df.itertuples(index=False):
            start = pd.to_datetime(r.start_date).to_period("W").start_time
            end = pd.to_datetime(r.end_date).to_period("W").start_time
            weeks = pd.date_range(start, end, freq="W-MON")
            for w in weeks:
                rows.append((int(r.product_id), pd.to_datetime(w), 1))
        if not rows:
            return pd.DataFrame(columns=["product_id","week","promo_flag"])
        out = pd.DataFrame(rows, columns=["product_id","week","promo_flag"]).drop_duplicates()
        return out

    def _make_features_for_next_week(self, weekly: pd.DataFrame, pid: int, price: float,
                                    comp_median: float, promo_flag: int) -> np.ndarray:
        g = weekly[weekly["product_id"] == pid].sort_values("week")
        y = g["qty_week"].values.astype(float)

        if len(y) < 4:
            raise ValueError("Historique insuffisant (<4 semaines) pour pricing ML.")

        lag1, lag2, lag3, lag4 = y[-1], y[-2], y[-3], y[-4]
        roll_mean_4 = float(np.mean([lag1, lag2, lag3, lag4]))
        roll_std_4 = float(np.std([lag1, lag2, lag3, lag4]))

        # season simple
        last_week = g["week"].iloc[-1]
        weekofyear = int(pd.to_datetime(last_week).isocalendar().week)

        X = np.array([[
            float(pid),
            float(price),
            float(comp_median),
            float(promo_flag),
            float(lag1), float(lag2), float(lag3), float(lag4),
            roll_mean_4, roll_std_4,
            float(weekofyear)
        ]], dtype=float)
        return X

    def recommend_price_ml(self, product: dict, sales: pd.DataFrame,
                           competitor_prices: pd.DataFrame, promotions: pd.DataFrame) -> dict:
        # charger modèles quantiles
        m10 = self.store.load_latest("price_demand_p10", "price_demand_p10_")
        m50 = self.store.load_latest("price_demand_p50", "price_demand_p50_")
        m90 = self.store.load_latest("price_demand_p90", "price_demand_p90_")

        weekly = self._build_weekly(sales)
        comp_week = self._competitor_week_median(competitor_prices)
        promo_week = self._promo_flag_week(promotions)

        pid = int(product["product_id"])
        cost = float(product["cost_price"])
        min_price = float(product["min_price"])
        current_price = float(product["current_price"])

        # contexte semaine la plus récente
        g = weekly[weekly["product_id"] == pid].sort_values("week")
        if g.empty:
            raise ValueError("Pas de ventes pour ce produit.")

        last_week = g["week"].iloc[-1]
        comp_row = comp_week[(comp_week["product_id"] == pid) & (comp_week["week"] == last_week)]
        comp_median = float(comp_row["comp_median"].iloc[0]) if not comp_row.empty else float(current_price)

        promo_row = promo_week[(promo_week["product_id"] == pid) & (promo_week["week"] == last_week)]
        promo_flag = int(promo_row["promo_flag"].iloc[0]) if not promo_row.empty else 0

        # simulation prix candidats (optimisation)
        # (ce n'est pas "règles métier", c'est une recherche de l'optimum du modèle)
        low = max(min_price, current_price * 0.80)
        high = max(low + 1.0, current_price * 1.20, comp_median * 1.10)
        candidates = np.linspace(low, high, 25)

        best = None
        for p in candidates:
            X = self._make_features_for_next_week(weekly, pid, p, comp_median, promo_flag)
            q50 = float(max(0.0, m50.predict(X)[0]))
            profit = (float(p) - cost) * q50
            if (best is None) or (profit > best["profit"]):
                q10 = float(max(0.0, m10.predict(X)[0]))
                q90 = float(max(0.0, m90.predict(X)[0]))
                best = {"price": float(p), "q10": q10, "q50": q50, "q90": q90, "profit": float(profit)}

        # impact estimé vs prix actuel
        X_cur = self._make_features_for_next_week(weekly, pid, current_price, comp_median, promo_flag)
        cur_q50 = float(max(0.0, m50.predict(X_cur)[0]))
        cur_profit = (current_price - cost) * cur_q50
        impact_profit = float(best["profit"] - cur_profit)

        direction = "INCREASE" if best["price"] > current_price else "DECREASE" if best["price"] < current_price else "KEEP"
        delta_price_pct = (best["price"] - current_price) / max(current_price, 1e-6) * 100.0
        delta_demand_pct = (best["q50"] - cur_q50) / max(cur_q50, 1e-6) * 100.0

        explanation = (
        f"Prix actuel={current_price:.2f}, recommandé={best['price']:.2f} ({direction}, {delta_price_pct:.1f}%). "
        f"Concurrence médiane≈{comp_median:.2f}, promo_active={promo_flag}. "
        f"Demande prévue (p50) au prix actuel≈{cur_q50:.2f}/sem, au prix recommandé≈{best['q50']:.2f}/sem ({delta_demand_pct:.1f}%). "
        f"Marge prévue/sem: actuelle≈{cur_profit:.2f}, nouvelle≈{best['profit']:.2f}, impact≈{impact_profit:.2f}."
        )
        return {
            "product_id": pid,
            "demand_weekly": {"p10": best["q10"], "p50": best["q50"], "p90": best["q90"]},
            "recommended_price": round(best["price"], 2),
            "interval": {"low": round(float(low), 2), "high": round(float(high), 2)},
            "direction": direction,
            "estimated_margin_impact_week": round(impact_profit, 4),
            "explanation": explanation,
        }