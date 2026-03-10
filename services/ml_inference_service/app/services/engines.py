import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional

def explain_price(rule: Dict[str, Any], recommended: float, direction: str) -> str:
    comp = rule.get("competitor_median")
    if comp is None:
        return f"Aucune donnée concurrentielle: recommandation basée sur min_price, marge min et prix actuel ({direction})."
    return f"Prix concurrent médian {comp:.2f} détecté: ajustement {direction} pour rester compétitif tout en respectant min_price et marge."

def price_recommendation(rule: Dict[str, Any], expected_qty_week: float) -> Dict[str, Any]:
    # Récupération des régles de pricing
    min_price = rule["min_price"]
    cost = rule["cost_price"]
    cur = rule["current_price"]
    comp = rule.get("competitor_median")

   
    if comp is not None:
        target = comp * 0.98 # si concurrent existe on vise 2% en dessous
    else:
        target = max(min_price, cost * (1.0 + rule["min_margin"]))
        #sinon on vise juste une marge minimale
    
    # garantir que le prix recommandé respecte le min_price
    recommended = float(max(min_price, target))
    # déterminer la direction du changement (augmentation, baisse, ou maintien)
    direction = "INCREASE" if recommended > cur else "DECREASE" if recommended < cur else "KEEP"

    # intervalle de prix ±5%
    low = float(max(min_price, recommended * 0.95))
    high = float(recommended * 1.05)

    # impact estimé à 1 semaine
    margin_cur = (cur - cost) * expected_qty_week
    margin_new = (recommended - cost) * expected_qty_week
    impact = float(margin_new - margin_cur)

    return {
        "recommended_price": recommended,
        "interval": {"low": low, "high": high},
        "direction": direction,
        "estimated_margin_impact_week": impact,
        "explanation": explain_price(rule, recommended, direction),
    }

def restock_recommendation(restock_rule: Dict[str, Any], demand_pred: Dict[str, Any]) -> Dict[str, Any]:
    stock = restock_rule["current_stock"]
    threshold_min = restock_rule["threshold_min"] #seuil min
    lead_days = restock_rule["lead_time_days"]

    # Demande lead time approximée : demand_week * (lead_days/7)
    p50 = demand_pred["p50"]
    p90 = demand_pred["p90"]
    lead_factor = lead_days / 7.0

    need_p50 = p50 * lead_factor
    need_p90 = p90 * lead_factor

    target_level = max(threshold_min, int(np.ceil(need_p50 + threshold_min)))
    qty = max(0, int(np.ceil(target_level - stock)))

    qty_low = max(0, int(np.floor(max(threshold_min, need_p50) - stock)))
    qty_high = max(qty, int(np.ceil(max(threshold_min, need_p90 + threshold_min) - stock)))

    explanation = (
        f"Réassort basé sur stock actuel={stock}, seuil_min={threshold_min}, lead_time={lead_days}j "
        f"et demande prévue (p50={p50:.1f}, p90={p90:.1f})."
    )
    impact = {
        "stockout_risk_reduction": "HIGH" if stock < threshold_min else "MEDIUM",
        "estimated_units_covered_lead_time_p50": float(need_p50),
    }

    return {
        "recommended_qty": qty,
        "interval": {"low": qty_low, "high": qty_high},
        "lead_time_days": lead_days,
        "explanation": explanation,
        "estimated_impact": impact,
    }

def detect_anomalies_for_product(
    product_row: Dict[str, Any],
    competitor_prices: pd.DataFrame,
    anomaly_rules: Dict[str, Any]
) -> Dict[str, Any]:
    pid = int(product_row["product_id"])
    cost = float(product_row["cost_price"])
    cur = float(product_row["current_price"])

    df = competitor_prices[competitor_prices["product_id"] == pid].copy()
    if df.empty:
        return {"product_id": pid, "anomalies": []}

    df["collected_at"] = pd.to_datetime(df["collected_at"])
    df = df.sort_values("collected_at")
    latest = df.groupby("competitor_id", as_index=False).tail(1)

    anomalies = []
    # prix trop bas vs coût
    too_low = latest[latest["competitor_price"] < cost * anomaly_rules["competitor_price_too_low_vs_cost"]]
    if not too_low.empty:
        anomalies.append({
            "type": "SUSPECT_COMPETITOR_PRICE_TOO_LOW",
            "severity": "HIGH",
            "detail": f"{len(too_low)} prix concurrents < ~{anomaly_rules['competitor_price_too_low_vs_cost']*100:.0f}% du coût."
        })

    # choc concurrentiel (variation)
    med = latest["competitor_price"].median()
    if med > 0:
        pct = abs(cur - med) / med
        if pct >= anomaly_rules["competitor_price_jump_pct"]:
            anomalies.append({
                "type": "COMPETITIVE_SHOCK",
                "severity": "MEDIUM",
                "detail": f"Écart prix vs médiane concurrence ~{pct*100:.0f}% (cur={cur:.2f}, med={med:.2f})."
            })

    # status != OK
    bad = latest[latest["status"] != "OK"]
    if not bad.empty:
        anomalies.append({
            "type": "SCRAPING_STATUS_NOT_OK",
            "severity": "LOW",
            "detail": f"{len(bad)} entrées scrapées avec status != OK."
        })

    return {"product_id": pid, "anomalies": anomalies}

def build_weekly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    """
    Agrège les ventes par semaine et par produit.
    attend sales.csv avec colonnes: timestamp, product_id, qty
    """
    df = sales.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["week"] = df["timestamp"].dt.to_period("W").dt.start_time
    weekly = df.groupby(["product_id", "week"], as_index=False)["qty"].sum()
    return weekly.sort_values(["product_id", "week"])