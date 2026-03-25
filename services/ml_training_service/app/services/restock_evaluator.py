import pandas as pd

from ..core.config import DATA_DIR, MODELS_DIR
from services.ml_inference_service.app.services.demand_predictor import DemandPredictor
from services.ml_inference_service.app.services.restock_engine import RestockMLEngine


def evaluate_restock_model():
    """
    Évaluation métier du moteur de réassort :
    - quantité moyenne recommandée
    - rupture attendue moyenne
    - surstock attendu moyen
    - coût attendu moyen
    """
    products = pd.read_csv(DATA_DIR / "products.csv")

    demand_predictor = DemandPredictor(DATA_DIR, MODELS_DIR)
    engine = RestockMLEngine()

    results = []

    for _, row in products.iterrows():
        product = row.to_dict()
        pid = int(product["product_id"])

        try:
            demand_pred = demand_predictor.predict_weekly(pid)

            rec = engine.recommend(
                product=product,
                demand_pred=demand_pred
            )

            results.append({
                "product_id": pid,
                "recommended_qty": float(rec["recommended_qty"]),
                "expected_stockout_units": float(rec["estimated_impact"]["expected_stockout_units"]),
                "expected_overstock_units": float(rec["estimated_impact"]["expected_overstock_units"]),
                "expected_cost": float(rec["estimated_impact"]["expected_cost"]),
            })

        except Exception:
            # Ignore les produits sans historique suffisant
            continue

    df = pd.DataFrame(results)

    if df.empty:
        return {
            "products_evaluated": 0,
            "metrics": {},
            "message": "Aucun produit n'a pu être évalué."
        }

    metrics = {
        "avg_recommended_qty": round(float(df["recommended_qty"].mean()), 4),
        "avg_expected_stockout_units": round(float(df["expected_stockout_units"].mean()), 4),
        "avg_expected_overstock_units": round(float(df["expected_overstock_units"].mean()), 4),
        "avg_expected_cost": round(float(df["expected_cost"].mean()), 4),
        "positive_restock_percent": round(float((df["recommended_qty"] > 0).mean() * 100.0), 4),
    }

    explanation = {
        "avg_recommended_qty": "Quantité moyenne de réapprovisionnement recommandée par produit.",
        "avg_expected_stockout_units": "Nombre moyen d’unités en rupture attendu après la décision de réassort.",
        "avg_expected_overstock_units": "Nombre moyen d’unités en surstock attendu après la décision.",
        "avg_expected_cost": "Coût moyen attendu (rupture + stockage) après optimisation.",
        "positive_restock_percent": "Pourcentage de produits pour lesquels une commande de réassort est recommandée."
    }

    return {
        "products_evaluated": int(len(df)),
        "metrics": metrics,
        "explanation": explanation
    }