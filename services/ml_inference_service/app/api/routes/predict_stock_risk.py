from fastapi import APIRouter
from ...core.config import MODELS_DIR
from ...services.model_store import ModelStore
from ...services.stock_risk_predictor import StockRiskPredictor
from ...schemas.stock_risk_schemas import StockRiskResponse

router = APIRouter(prefix="/predict")
store = ModelStore(MODELS_DIR)
#pour charger les modèles sauvegardés
predictor = StockRiskPredictor()

@router.get("/stock-risk/{product_id}", response_model=StockRiskResponse)
def predict_stock_risk(product_id: int):
    demand_model = store.load_latest("demand", "demand_weekly_")
    restock_rules = store.load_latest("restock_rules", "restock_rules_")

    demand_stats = demand_model.per_product.get(product_id, {"p50": 0.0, "p90": 0.0})
    restock_rule = restock_rules.get(product_id)
    if not restock_rule:
        # on laisse FastAPI gérer la réponse simple
        return {
            "product_id": product_id,
            "risk": "OK",
            "probability": 0.0,
            "inputs": {
                "current_stock": 0,
                "threshold_min": 0,
                "threshold_max": 0,
                "demand_weekly_p50": 0.0,
                "demand_weekly_p90": 0.0,
                "lead_time_days": 7,
            },
            "explanation": "Produit introuvable dans restock_rules.",
        }

    return predictor.predict(
        product_id=product_id,
        demand_stats=demand_stats,
        restock_rule=restock_rule,
    )
# Cette route sert à prédire le risque de stock d’un produit à partir
# de modèles déjà entraînés et de règles de réapprovisionnement sauvegardées.
# Elle commence par charger le dernier modèle de demande ainsi que 
# les dernières restock_rules, puis elle récupère pour le product_id demandé 
# les statistiques de demande (p50, p90) et les règles de stock correspondantes. Si aucune règle
# n’existe pour ce produit, elle retourne une réponse par défaut avec des valeurs nulles pour éviter une erreur. 
# Sinon, elle envoie toutes ces informations au service StockRiskPredictor, qui calcule le niveau de risque et renvoie le résultat final 
# sous le format défini par StockRiskResponse.