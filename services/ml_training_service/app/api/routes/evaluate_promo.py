from fastapi import APIRouter, HTTPException
from ...services.promo_evaluator import evaluate_promo_model

router = APIRouter(prefix="/evaluate")


@router.post("/promo-ml")
def evaluate_promo():
    try:
        return evaluate_promo_model()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))