from dataclasses import dataclass
from typing import Dict, Any
from ..schemas.stock_risk_schemas import StockRiskResponse, StockRiskInputs


@dataclass
class StockRiskPredictor:
    """
    Détermine le risque STOCKOUT / OVERSTOCK / OVERSTOCK_CRITIQUE / OK à partir:
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

        # Couverture du stock en semaines selon la demande médiane
        if demand_p50 > 0:
            stock_coverage_weeks = stock / demand_p50
        else:
            stock_coverage_weeks = float("inf")

        # Seuil métier pour considérer un surstock critique
        # Ici : plus de 12 semaines de couverture
        critical_coverage_weeks = 12

        if stock_after_lead < min_th:
            risk = "STOCKOUT"
            gap = min_th - stock_after_lead
            prob = min(0.95, 0.50 + gap / max(1.0, float(min_th)))
            explanation = (
                f"Le produit présente un risque élevé de rupture. "
                f"Le stock actuel est de {stock} unités, alors que la demande estimée pendant le délai d’approvisionnement "
                f"peut atteindre environ {projected_lead_need:.1f} unités dans un scénario de consommation soutenue. "
                f"Le stock projeté après délai serait d’environ {stock_after_lead:.1f} unités, "
                f"soit en dessous du seuil minimal de {min_th}. "
                f"Un réapprovisionnement rapide est recommandé."
            )

        elif stock > max_th and stock_coverage_weeks > critical_coverage_weeks:
            risk = "OVERSTOCK_CRITIQUE"
            excess = stock - max_th
            prob = min(0.98, 0.60 + excess / max(1.0, float(max_th)))
            explanation = (
                f"Le produit présente un surstock critique. "
                f"Le stock actuel est de {stock} unités, ce qui dépasse le seuil maximal de {max_th}. "
                f"En plus, ce niveau de stock représente environ {stock_coverage_weeks:.1f} semaines de couverture "
                f"sur la base d’une demande hebdomadaire médiane estimée à {demand_p50:.1f} unités. "
                f"Ce volume est très élevé par rapport au rythme de consommation attendu. "
                f"Il est recommandé de suspendre ou ralentir les réapprovisionnements et d’envisager des actions d’écoulement."
            )

        elif stock > max_th:
            risk = "OVERSTOCK"
            excess = stock - max_th
            prob = min(0.90, 0.45 + excess / max(1.0, float(max_th)))
            explanation = (
                f"Le produit présente un risque de surstock. "
                f"Le stock actuel atteint {stock} unités, ce qui dépasse le seuil maximal de {max_th}. "
                f"Cependant, le niveau n’est pas encore jugé critique au regard de la couverture estimée, "
                f"qui est d’environ {stock_coverage_weeks:.1f} semaines. "
                f"Il peut être pertinent de surveiller le rythme de consommation et de modérer les prochains réapprovisionnements."
            )

        else:
            risk = "OK"
            prob = 0.10
            explanation = (
                f"Le niveau de stock est actuellement maîtrisé. "
                f"Avec {stock} unités disponibles, le produit reste dans une zone acceptable entre le seuil minimal "
                f"({min_th}) et le seuil maximal ({max_th}). "
                f"La couverture estimée est d’environ {stock_coverage_weeks:.1f} semaines, "
                f"et aucune alerte immédiate de rupture ou de surstock n’est détectée."
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
            risk=risk,
            probability=float(prob),
            inputs=inputs,
            explanation=explanation,
        )