import pandas as pd
import numpy as np

from ..core.config import DATA_DIR, MODELS_DIR, REPORTS_DIR
from services.ml_inference_service.app.services.model_store import ModelStore
from services.ml_inference_service.app.services.price_engine import PriceMLRecommender


def evaluate_pricing_model():
    # charger les données
    products = pd.read_csv(DATA_DIR / "products.csv")
    sales = pd.read_csv(DATA_DIR / "sales.csv")
    competitor_prices = pd.read_csv(DATA_DIR / "competitor_prices.csv")
    promotions = pd.read_csv(DATA_DIR / "promotions.csv")

    # charger le moteur ML pricing
    store = ModelStore(MODELS_DIR)
    engine = PriceMLRecommender(store=store, reports_dir=REPORTS_DIR)

    results = []

    for _, row in products.iterrows():
        product = row.to_dict()
        pid = int(product["product_id"])

        try:
            rec = engine.recommend_price_ml(
                product=product,
                sales=sales,
                competitor_prices=competitor_prices,
                promotions=promotions
            )

            current_price = float(product["current_price"])
            cost_price = float(product["cost_price"])

            # Demande prévue actuelle et recommandée
            demand_p50_new = float(rec["demand_weekly"]["p50"])

            # Pour estimer la marge actuelle, on relit l'explication si besoin,
            # mais ici on peut recalculer proprement avec les données du moteur :
            # le moteur renvoie directement estimated_margin_impact_week
            margin_gain = float(rec["estimated_margin_impact_week"])

            # Marge actuelle approximée à partir de la demande au prix recommandé
            # (version simple pour comparaison métier)
            margin_new = (float(rec["recommended_price"]) - cost_price) * demand_p50_new
            margin_current_est = margin_new - margin_gain

            results.append({
                "product_id": pid,
                "current_price": current_price,
                "recommended_price": float(rec["recommended_price"]),
                "direction": rec["direction"],
                "margin_current_est": float(margin_current_est),
                "margin_new_est": float(margin_new),
                "margin_gain": float(margin_gain),
                "demand_p50_new": demand_p50_new,
            })

        except Exception:
            # on ignore les produits sans historique suffisant
            continue

    df = pd.DataFrame(results)

    if df.empty:
        return {
            "products_evaluated": 0,
            "metrics": {},
            "message": "Aucun produit n'a pu être évalué."
        }

    metrics = {
        "avg_current_margin_est": round(float(df["margin_current_est"].mean()), 4),
        "avg_recommended_margin_est": round(float(df["margin_new_est"].mean()), 4),
        "avg_margin_gain": round(float(df["margin_gain"].mean()), 4),
        "positive_recommendations_percent": round(float((df["margin_gain"] > 0).mean() * 100.0), 4),
        "increase_percent": round(float((df["direction"] == "INCREASE").mean() * 100.0), 4),
        "decrease_percent": round(float((df["direction"] == "DECREASE").mean() * 100.0), 4),
        "keep_percent": round(float((df["direction"] == "KEEP").mean() * 100.0), 4),
        "avg_recommended_price": round(float(df["recommended_price"].mean()), 4),
    }

    explanation = {
        "avg_current_margin_est": "Marge hebdomadaire moyenne estimée avec le prix actuel.",
        "avg_recommended_margin_est": "Marge hebdomadaire moyenne estimée avec le prix recommandé par le modèle.",
        "avg_margin_gain": "Gain moyen de marge hebdomadaire estimé grâce à la recommandation.",
        "positive_recommendations_percent": "Pourcentage de produits pour lesquels la recommandation améliore la marge estimée.",
        "increase_percent": "Pourcentage de recommandations proposant une augmentation de prix.",
        "decrease_percent": "Pourcentage de recommandations proposant une baisse de prix.",
        "keep_percent": "Pourcentage de recommandations proposant de garder le même prix.",
        "avg_recommended_price": "Prix recommandé moyen sur les produits évalués."
    }

    return {
        "products_evaluated": int(len(df)),
        "metrics": metrics,
        "explanation": explanation
    }
    
# A. Restock
# Le code :
# lit tous les produits
# prédit la demande de chaque produit
# calcule la recommandation de réassort
# récupère les impacts estimés
# calcule les moyennes globales
# Ce que ça te dira
# si ton modèle recommande souvent une commande
# si la rupture attendue reste faible
# si le surstock reste raisonnable
# si le coût attendu est cohérent
