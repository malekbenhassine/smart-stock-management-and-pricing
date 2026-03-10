import numpy as np

class RestockMLEngine:
    """
    ML prescriptive (pas rules):
    - utilise la distribution de demande (p10/p50/p90) sur le lead time
    - choisit Q qui minimise un coût attendu: rupture vs stockage
    """
    def __init__(self):
        pass

    def recommend(self, product: dict, demand_pred: dict) -> dict:
        pid = int(product["product_id"])

        current_stock = float(product.get("current_stock", 0))
        threshold_min = float(product.get("threshold_min", 0))
        threshold_max = float(product.get("threshold_max", 10**9))
        lead_days = int(product.get("lead_time_days", 7))

        # coûts (si tu ne les as pas dans products.csv => constants PFE justifiables)
        stockout_cost = float(product.get("stockout_cost", 15.0))  # coût rupture / unité
        holding_cost = float(product.get("holding_cost", 1.0))     # coût stockage / unité

        # Demande sur lead time
        lead_factor = lead_days / 7.0
        mu = float(demand_pred["p50"]) * lead_factor
        sigma = max(1e-6, (float(demand_pred["p90"]) - float(demand_pred["p10"])) / 2.56) * lead_factor

        # Monte Carlo
        rng = np.random.default_rng(42)
        sims = rng.normal(loc=mu, scale=sigma, size=5000)
        sims = np.clip(sims, 0, None)

        # Candidats Q
        Q_max = int(np.ceil(mu + 3*sigma + threshold_min + 10))
        Q_candidates = np.arange(0, max(1, Q_max + 1), 1)

        best = None
        for Q in Q_candidates:
            future = current_stock + Q - sims
            shortage = np.clip(-future, 0, None)
            overage = np.clip(future, 0, None)

            over_max = max(0.0, (current_stock + Q) - threshold_max)
            penalty = 2.0 * over_max  # pénalité douce si dépassement max

            expected_cost = stockout_cost * shortage.mean() + holding_cost * overage.mean() + penalty
            if (best is None) or (expected_cost < best["expected_cost"]):
                best = {"Q": int(Q), "expected_cost": float(expected_cost),
                        "shortage": float(shortage.mean()), "overage": float(overage.mean())}

        # Intervalle (data-driven via p10/p90)
        need_p10 = float(demand_pred["p10"]) * lead_factor
        need_p90 = float(demand_pred["p90"]) * lead_factor

        q_low = int(max(0, np.floor(max(threshold_min, need_p10 + threshold_min) - current_stock)))
        q_high = int(max(best["Q"], np.ceil(max(threshold_min, need_p90 + threshold_min) - current_stock)))

        explanation = (
            f"Restock ML prescriptif: optimisation du coût attendu (rupture vs stockage). "
            f"Stock={current_stock:.0f}, lead_time={lead_days}j, besoin lead-time p50≈{mu:.2f}. "
            f"Q optimal={best['Q']} (E[rupture]≈{best['shortage']:.2f}, E[surstock]≈{best['overage']:.2f})."
        )

        return {
            "product_id": pid,
            "recommended_qty": best["Q"],
            "interval": {"low": q_low, "high": q_high},
            "lead_time_days": lead_days,
            "explanation": explanation,
            "estimated_impact": {
                "expected_stockout_units": round(best["shortage"], 4),
                "expected_overstock_units": round(best["overage"], 4),
                "expected_cost": round(best["expected_cost"], 4),
            }
        }