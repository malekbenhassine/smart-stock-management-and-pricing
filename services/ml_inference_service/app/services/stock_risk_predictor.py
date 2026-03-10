from dataclasses import dataclass
from typing import Dict, Any
from ..schemas.stock_risk_schemas import StockRiskResponse, StockRiskInputs

@dataclass
class StockRiskPredictor:
    """
    Détermine le risque STOCKOUT / OVERSTOCK / OK à partir:
    - demand forecast (p50/p90)
    - stock + seuils
    - lead_time
    """
    def predict(
        self,
        product_id: int,
        demand_stats: Dict[str, Any],
        restock_rule: Dict[str, Any],
    ) -> StockRiskResponse:
        stock = int(restock_rule["current_stock"])
        min_th = int(restock_rule["threshold_min"])
        max_th = int(restock_rule["threshold_max"])
        lead_days = int(restock_rule.get("lead_time_days", 7))
        lead_factor = lead_days / 7.0

        demand_p50 = float(demand_stats.get("p50", 0.0))
        demand_p90 = float(demand_stats.get("p90", demand_p50))

        projected_lead_need = demand_p90 * lead_factor
        stock_after_lead = stock - projected_lead_need

        # Règles (MVP)
        if stock_after_lead < min_th:
            risk = "STOCKOUT"
            gap = (min_th - stock_after_lead)
            prob = min(0.95, 0.50 + gap / max(1.0, float(min_th)))
            explanation = (
                f"Risque de rupture: stock={stock}, besoin lead-time(p90)≈{projected_lead_need:.1f}, "
                f"stock après lead≈{stock_after_lead:.1f} < seuil_min={min_th}."
            )
        elif stock > max_th + demand_p50 * 4:
            risk = "OVERSTOCK"
            excess = (stock - max_th)
            prob = min(0.90, 0.45 + excess / max(1.0, float(max_th)))
            explanation = (
                f"Risque de surstock: stock={stock} > seuil_max={max_th} "
                f"+ couverture 4 semaines(p50)≈{(demand_p50*4):.1f}."
            )
        else:
            risk = "OK"
            prob = 0.10
            explanation = (
                f"Stock OK: stock={stock}, seuils=[{min_th},{max_th}], "
                f"besoin lead-time(p90)≈{projected_lead_need:.1f}."
            )

        inputs = StockRiskInputs(
            current_stock=stock,
            threshold_min=min_th,
            threshold_max=max_th,
            demand_weekly_p50=demand_p50,
            demand_weekly_p90=demand_p90,
            lead_time_days=lead_days,
        )

        return StockRiskResponse(
            product_id=product_id,
            risk=risk,                 # type: ignore
            probability=float(prob),
            inputs=inputs,
            explanation=explanation,
        )
        