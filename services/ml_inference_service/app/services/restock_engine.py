import math
import numpy as np
import pandas as pd


class RestockMLEngine:
    """
    Algorithme de recommandation de réassort basé sur :

    - la demande prédite (p10, p50, p90)
    - le lead time fournisseur réel depuis product_suppliers.csv
    - le fournisseur préféré si disponible
    - un stock de sécurité
    - une logique de type (s, S)

    Règle métier importante :
    si le stock est en rupture ou sous le seuil minimal,
    la quantité recommandée doit au minimum permettre
    de revenir au seuil minimal.
    """

    def __init__(self, service_level: float = 0.95, review_period_days: int = 7):
        self.service_level = service_level
        self.review_period_days = review_period_days

    def _to_bool(self, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in ["true", "1", "yes", "y"]

    def _get_z_value(self, service_level: float) -> float:
        if service_level >= 0.99:
            return 2.33
        if service_level >= 0.98:
            return 2.05
        if service_level >= 0.97:
            return 1.88
        if service_level >= 0.95:
            return 1.65
        if service_level >= 0.90:
            return 1.28
        return 1.0

    def _select_supplier(self, supplier_rows: pd.DataFrame) -> dict:
        rows = supplier_rows.copy()

        if "is_preferred" in rows.columns:
            rows["is_preferred"] = rows["is_preferred"].apply(self._to_bool)
        else:
            rows["is_preferred"] = False

        if "lead_time_days" not in rows.columns:
            rows["lead_time_days"] = 7

        if "last_cost_price" not in rows.columns:
            rows["last_cost_price"] = 0

        rows["lead_time_days"] = pd.to_numeric(rows["lead_time_days"], errors="coerce").fillna(7)
        rows["last_cost_price"] = pd.to_numeric(rows["last_cost_price"], errors="coerce").fillna(0)

        preferred_rows = rows[rows["is_preferred"] == True]

        if not preferred_rows.empty:
            chosen = preferred_rows.sort_values(
                by=["lead_time_days", "last_cost_price"],
                ascending=[True, True]
            ).iloc[0]
        else:
            chosen = rows.sort_values(
                by=["last_cost_price", "lead_time_days"],
                ascending=[True, True]
            ).iloc[0]

        return chosen.to_dict()

    def recommend(self, product: dict, demand_pred: dict, supplier_rows: pd.DataFrame) -> dict:
        product_id = int(product["product_id"])

        current_stock = float(product.get("current_stock", 0) or 0)
        threshold_min = float(product.get("threshold_min", 0) or 0)
        threshold_max = float(product.get("threshold_max", 999999) or 999999)

        supplier = self._select_supplier(supplier_rows)
        supplier_id = int(supplier.get("supplier_id"))
        lead_time_days = int(float(supplier.get("lead_time_days", 7) or 7))
        last_cost_price = float(supplier.get("last_cost_price", 0) or 0)

        p10 = float(demand_pred.get("p10", 0) or 0)
        p50 = float(demand_pred.get("p50", 0) or 0)
        p90 = float(demand_pred.get("p90", 0) or 0)

        lead_factor = lead_time_days / 7.0
        review_factor = self.review_period_days / 7.0

        demand_lead_p10 = p10 * lead_factor
        demand_lead_p50 = p50 * lead_factor
        demand_lead_p90 = p90 * lead_factor

        sigma_week = max(0.0001, (p90 - p10) / 2.56)
        sigma_lead = sigma_week * math.sqrt(max(lead_factor, 0.0001))

        z = self._get_z_value(self.service_level)
        safety_stock = z * sigma_lead

        reorder_point = math.ceil(demand_lead_p50 + safety_stock)

        extra_cycle_stock = math.ceil(p50 * review_factor)
        target_level = math.ceil(demand_lead_p50 + safety_stock + extra_cycle_stock)

        target_level = max(target_level, math.ceil(threshold_min))
        target_level = min(target_level, math.ceil(threshold_max))

        min_recovery_qty = max(0, math.ceil(threshold_min - current_stock))

        if current_stock <= reorder_point:
            recommended_qty = max(0, math.ceil(target_level - current_stock))
        else:
            recommended_qty = 0

        recommended_qty = max(recommended_qty, min_recovery_qty if current_stock < threshold_min else 0)

        if current_stock <= 0 and recommended_qty == 0:
            recommended_qty = max(1, min_recovery_qty)

        low_target = max(
            math.ceil(threshold_min),
            math.floor(demand_lead_p10)
        )
        low_target = min(low_target, math.ceil(threshold_max))
        q_low = max(0, math.ceil(low_target - current_stock))

        high_target = max(
            math.ceil(threshold_min),
            math.ceil(demand_lead_p90 + safety_stock + extra_cycle_stock)
        )
        high_target = min(high_target, math.ceil(threshold_max))
        q_high = max(recommended_qty, math.ceil(high_target - current_stock))

        stock_status = "normal"
        if current_stock <= 0:
            stock_status = "rupture"
        elif current_stock < threshold_min:
            stock_status = "below_min"
        elif current_stock <= reorder_point:
            stock_status = "reorder"
        
        explanation = (
            f"Fournisseur retenu: {supplier_id}. "
            f"Lead time: {lead_time_days} jours. "
            f"Demande prévue pendant le lead time (p50): {demand_lead_p50:.2f}. "
            f"Stock de sécurité: {safety_stock:.2f}. "
            f"Point de commande: {reorder_point}. "
            f"Niveau cible: {target_level}. "
            f"Stock actuel: {current_stock:.0f}. "
            f"Quantité recommandée: {recommended_qty}."
        )

        return {
            "product_id": product_id,
            "supplier_id": supplier_id,
            "recommended_qty": int(recommended_qty),
            "interval": {
                "low": int(q_low),
                "high": int(q_high)
            },
            "lead_time_days": int(lead_time_days),
            "last_cost_price": round(last_cost_price, 2),
            "reorder_point": int(reorder_point),
            "safety_stock": round(float(safety_stock), 2),
            "target_level": int(target_level),
            "stock_status": stock_status,
            "service_level": self.service_level,
            "explanation": explanation,
            "estimated_impact": {
                "forecast_p10_lead_time": round(float(demand_lead_p10), 2),
                "forecast_p50_lead_time": round(float(demand_lead_p50), 2),
                "forecast_p90_lead_time": round(float(demand_lead_p90), 2)
            }
        }
#le système lit bien product_suppliers.csv
# il prend le fournisseur préféré
# il utilise le lead time réel
# il calcule un stock de sécurité
# il applique une logique (s, S) :
# s = reorder_point s = le seuil de déclenchement => s dit quand agir =>s = demande pendant le lead time + stock de sécurité
# S = target_level S = le niveau cible => S dit jusqu’où remplir => S = s + stock supplémentaire de couverture (estimation unesemaine lkodem)
# si stock ≤ s, il recommande S - stock
# si stock < threshold_min, il force au moins le retour au seuil minimal
# si rupture, la reco ne reste plus à 0
# Petit test mental
# Si :
# current_stock = 0
# threshold_min = 20
# lead_time_days = 14
# p50 = 10
# Alors :
# demande lead time ≈ 20
# avec sécurité + couverture supplémentaire, la reco sera bien > 20
# donc plus de cas où rupture = quantité absurde