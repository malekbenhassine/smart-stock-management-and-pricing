import numpy as np
import pandas as pd

class PromoMLEngine:
    """
    ML Promo:
    - prédit qty_week quantiles en fonction (discount, concurrence, lags, season)
    - simule des discounts et choisit celui qui maximise l'objectif:
      si surstock -> maximiser unités vendues
      sinon -> maximiser marge prévue
    """
    def __init__(self, store):
        self.store = store

    def _build_weekly(self, sales: pd.DataFrame) -> pd.DataFrame:
        df = sales.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["week"] = df["timestamp"].dt.to_period("W").dt.start_time
        g = df.groupby(["product_id","week"], as_index=False).agg(
            qty_week=("qty","sum"),
            price_week=("unit_price","mean")
        )
        return g.sort_values(["product_id","week"])

    def _competitor_week_median(self, competitor_prices: pd.DataFrame) -> pd.DataFrame:
        df = competitor_prices.copy()
        df["collected_at"] = pd.to_datetime(df["collected_at"])
        df["week"] = df["collected_at"].dt.to_period("W").dt.start_time
        med = df.groupby(["product_id","week"], as_index=False)["competitor_price"].median()
        return med.rename(columns={"competitor_price":"comp_median"})

    def _make_X(self, weekly: pd.DataFrame, pid: int, price_week: float, comp_median: float,
                promo_flag: int, discount: float) -> np.ndarray:
        #construit les features que le modéle ML 
        g = weekly[weekly["product_id"] == pid].sort_values("week")
        y = g["qty_week"].values.astype(float)
        if len(y) < 4:
            raise ValueError("Historique insuffisant (<4 semaines) pour promo ML.")

        lag1, lag2, lag3, lag4 = y[-1], y[-2], y[-3], y[-4]
        roll_mean_4 = float(np.mean([lag1, lag2, lag3, lag4]))
        roll_std_4 = float(np.std([lag1, lag2, lag3, lag4]))

        last_week = g["week"].iloc[-1]
        weekofyear = int(pd.to_datetime(last_week).isocalendar().week)

        return np.array([[
            float(pid),
            float(price_week),
            float(comp_median),
            float(promo_flag),
            float(discount),
            float(lag1), float(lag2), float(lag3), float(lag4),
            roll_mean_4, roll_std_4,
            float(weekofyear),
        ]], dtype=float)

    def recommend(self, product: dict, sales: pd.DataFrame,
                  competitor_prices: pd.DataFrame) -> dict:
        pid = int(product["product_id"])
        cost = float(product["cost_price"])
        min_price = float(product["min_price"])
        current_price = float(product["current_price"])
        current_stock = float(product.get("current_stock", 0))
        threshold_max = float(product.get("threshold_max", current_stock + 1))

        m10 = self.store.load_latest("promo_demand_p10", "promo_demand_p10_")
        m50 = self.store.load_latest("promo_demand_p50", "promo_demand_p50_")
        m90 = self.store.load_latest("promo_demand_p90", "promo_demand_p90_")

        weekly = self._build_weekly(sales)
        comp_week = self._competitor_week_median(competitor_prices)

        g = weekly[weekly["product_id"] == pid].sort_values("week")
        if g.empty:
            raise ValueError("Pas de ventes pour ce produit.")

        last_week = g["week"].iloc[-1]
        comp_row = comp_week[(comp_week["product_id"] == pid) & (comp_week["week"] == last_week)]
        comp_median = float(comp_row["comp_median"].iloc[0]) if not comp_row.empty else float(current_price)

        # objectif: si surstock -> vendre +, sinon -> maximiser marge
        is_overstock = current_stock > threshold_max

        discounts = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
        best = None

        for d in discounts:
            promo_price = current_price * (1.0 - d)
            #calcul prix promo
            if promo_price < min_price:
                continue

            X = self._make_X(weekly, pid, promo_price, comp_median, promo_flag=1, discount=d)
            q50 = float(max(0.0, m50.predict(X)[0]))
            q10 = float(max(0.0, m10.predict(X)[0]))
            q90 = float(max(0.0, m90.predict(X)[0]))

            margin = (promo_price - cost) * q50
            #margin prévue pour ce prix promo
            score = q50 if is_overstock else margin  

            if (best is None) or (score > best["score"]):
                best = {
                    "discount": float(d),
                    "promo_price": float(promo_price),
                    "q10": q10, "q50": q50, "q90": q90,
                    "margin": float(margin),
                    "score": float(score),
                }

        if best is None:
            return {
                "product_id": pid,
                "should_promote": False,
                "recommended_discount": 0.0,
                "promo_price": current_price,
                "interval": {"low": current_price, "high": current_price},
                "estimated_impact": {"demand_weekly_p50": 0.0, "estimated_margin_week": 0.0},
                "explanation": "Promo ML: aucune remise feasible (min_price) ou données insuffisantes."
            }

        explanation = (
            f"Promo ML: simulation discounts et sélection selon {'écoulement surstock' if is_overstock else 'marge'}. "
            f"Discount={best['discount']*100:.0f}%, prix promo={best['promo_price']:.2f} (min_price={min_price:.2f}). "
            f"Demande prévue p50≈{best['q50']:.2f}/sem, marge prévue≈{best['margin']:.2f}/sem."
        )

        return {
            "product_id": pid,
            "should_promote": best["discount"] > 0.0,
            "recommended_discount": round(best["discount"], 4),
            "promo_price": round(best["promo_price"], 2),
            "interval": {"low": round(max(min_price, best["promo_price"]*0.95), 2),
                         "high": round(best["promo_price"]*1.05, 2)},
            "estimated_impact": {
                "demand_weekly": {"p10": best["q10"], "p50": best["q50"], "p90": best["q90"]},
                "estimated_margin_week": round(best["margin"], 4),
            },
            "explanation": explanation
        }