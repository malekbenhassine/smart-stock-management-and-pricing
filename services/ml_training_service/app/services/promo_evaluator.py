import pandas as pd

from ..core.config import DATA_DIR, MODELS_DIR
from services.ml_inference_service.app.services.model_store import ModelStore
from services.ml_inference_service.app.services.promo_engine import PromoMLEngine


def evaluate_promo_model():
    """
    Évaluation métier du moteur de promotion :
    - % produits avec promo recommandée
    - discount moyen
    - prix promo moyen
    - marge estimée moyenne
    - demande p50 moyenne estimée
    """
    products = pd.read_csv(DATA_DIR / "products.csv")
    sales = pd.read_csv(DATA_DIR / "sales.csv")
    competitor_prices = pd.read_csv(DATA_DIR / "competitor_prices.csv")

    store = ModelStore(MODELS_DIR)
    engine = PromoMLEngine(store=store)

    results = []

    for _, row in products.iterrows():
        product = row.to_dict()
        pid = int(product["product_id"])

        try:
            rec = engine.recommend(
                product=product,
                sales=sales,
                competitor_prices=competitor_prices
            )

            results.append({
                "product_id": pid,
                "should_promote": bool(rec["should_promote"]),
                "recommended_discount": float(rec["recommended_discount"]),
                "promo_price": float(rec["promo_price"]),
                "estimated_margin_week": float(rec["estimated_impact"]["estimated_margin_week"]),
                "predicted_demand_p50": float(rec["estimated_impact"]["demand_weekly"]["p50"]),
            })

        except Exception:
            continue

    df = pd.DataFrame(results)

    if df.empty:
        return {
            "products_evaluated": 0,
            "metrics": {},
            "message": "Aucun produit n'a pu être évalué."
        }

    metrics = {
        "promo_recommended_percent": round(float(df["should_promote"].mean() * 100.0), 4),
        "avg_discount": round(float(df["recommended_discount"].mean()), 4),
        "avg_promo_price": round(float(df["promo_price"].mean()), 4),
        "avg_estimated_margin_week": round(float(df["estimated_margin_week"].mean()), 4),
        "avg_predicted_demand_p50": round(float(df["predicted_demand_p50"].mean()), 4),
    }

    explanation = {
        "promo_recommended_percent": "Pourcentage de produits pour lesquels une promotion est recommandée.",
        "avg_discount": "Remise moyenne recommandée (0.10 = 10%).",
        "avg_promo_price": "Prix promotionnel moyen recommandé.",
        "avg_estimated_margin_week": "Marge hebdomadaire moyenne estimée après application de la promo recommandée.",
        "avg_predicted_demand_p50": "Demande hebdomadaire moyenne prédite (quantile p50) avec la promo recommandée."
    }

    return {
        "products_evaluated": int(len(df)),
        "metrics": metrics,
        "explanation": explanation
    }
    

# B. Promo
# Le code :
# lit les produits, ventes et prix concurrents
# lance le moteur promo sur chaque produit
# récupère discount, prix promo, marge et demande estimée
# calcule les moyennes globales
# Ce que ça te dira
# si ton moteur recommande trop de promos ou pas assez
# si les remises sont réalistes
# si la marge reste positive
# si la demande prévue augmente


# l’évaluation du moteur de promotion montre que les promotions
# sont rarement recommandées. Cela s’explique par la faible élasticité
# prix observée dans les données d’entraînement : la demande varie peu 
# lorsque le prix change. Par conséquent, une réduction de prix diminue 
# généralement la marge sans générer un gain significatif de volume