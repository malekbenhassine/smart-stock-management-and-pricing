import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any
from datetime import datetime

@dataclass
class DemandModel:
    # on stocke stats par produit
    per_product: Dict[int, Dict[str, Any]]
    horizon_weeks: int

def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    sales = sales.copy()
    sales["timestamp"] = pd.to_datetime(sales["timestamp"])
    sales["week"] = sales["timestamp"].dt.to_period("W").dt.start_time
    weekly = sales.groupby(["product_id", "week"], as_index=False)["qty"].sum()
    return weekly.sort_values(["product_id", "week"])

def train_demand_baseline(weekly_sales: pd.DataFrame, horizon_weeks: int = 4) -> DemandModel:
    per_product = {}
    for pid, g in weekly_sales.groupby("product_id"):
        y = g["qty"].values.astype(float)
        if len(y) < 4:
            # peu d'historique -> fallback
            p50 = float(np.mean(y)) if len(y) else 0.0
            resid = y - p50 if len(y) else np.array([0.0])
        else:
            # p50 = moyenne des 8 dernières semaines (ou moins si pas dispo)
            window = min(8, len(y))
            p50 = float(np.mean(y[-window:]))
            resid = y[-window:] - p50

        p10 = float(np.percentile(y, 10)) if len(y) else 0.0
        p90 = float(np.percentile(y, 90)) if len(y) else 0.0

        # intervalle par résidus (simple)
        r10 = float(np.percentile(resid, 10)) if len(resid) else 0.0
        r90 = float(np.percentile(resid, 90)) if len(resid) else 0.0

        per_product[int(pid)] = {
            "p50": p50,
            "p10": max(0.0, p50 + r10),
            "p90": max(0.0, p50 + r90),
            "history_weeks": int(len(y)),
            "last_week": str(g["week"].max()) if len(g) else None,
        }

    return DemandModel(per_product=per_product, horizon_weeks=horizon_weeks)

def train_price_rules(products: pd.DataFrame, competitor_prices: pd.DataFrame) -> Dict[int, Dict[str, Any]]:
    # on garde dernier prix concurrent par produit + médiane
    competitor_prices = competitor_prices.copy()
    competitor_prices["collected_at"] = pd.to_datetime(competitor_prices["collected_at"])
    competitor_prices = competitor_prices.sort_values("collected_at")

    latest = competitor_prices.groupby(["product_id", "competitor_id"], as_index=False).tail(1)
    med = latest.groupby("product_id")["competitor_price"].median().to_dict()

    rules = {}
    for _, p in products.iterrows():
        pid = int(p["product_id"])
        rules[pid] = {
            "min_price": float(p["min_price"]),
            "cost_price": float(p["cost_price"]),
            "current_price": float(p["current_price"]),
            "min_margin": float(p["min_margin"]),
            "competitor_median": float(med.get(pid)) if pid in med else None,
        }
    return rules

def train_restock_rules(products: pd.DataFrame, product_suppliers: pd.DataFrame) -> Dict[int, Dict[str, Any]]:
    # lead time préféré si dispo, sinon fallback 7j
    preferred = product_suppliers[product_suppliers.get("is_preferred", False) == True].copy()
    lead_map = {}
    if not preferred.empty:
        for pid, g in preferred.groupby("product_id"):
            lead_map[int(pid)] = int(g["lead_time_days"].iloc[0])
    rules = {}
    for _, p in products.iterrows():
        pid = int(p["product_id"])
        rules[pid] = {
            "threshold_min": int(p["threshold_min"]),
            "threshold_max": int(p["threshold_max"]),
            "current_stock": int(p["current_stock"]),
            "lead_time_days": int(lead_map.get(pid, 7)),
        }
    return rules

def train_anomaly_rules() -> Dict[str, Any]:
    return {
        "competitor_price_jump_pct": 0.30,  # 30%
        "competitor_price_too_low_vs_cost": 0.90,  # prix concurrent < 90% coût => suspect
        "sales_spike_z": 3.0,
    }