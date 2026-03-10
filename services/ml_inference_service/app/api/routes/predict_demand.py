from fastapi import APIRouter
from ...core.config import DATA_DIR, MODELS_DIR
from ...services.demand_predictor import DemandPredictor

router = APIRouter(prefix="/predict")
predictor = DemandPredictor(DATA_DIR, MODELS_DIR)

@router.get("/demand-weekly/{product_id}")
def predict_demand_weekly(product_id: int):
    return predictor.predict_weekly(product_id)