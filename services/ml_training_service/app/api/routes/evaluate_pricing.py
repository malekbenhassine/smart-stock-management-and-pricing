from fastapi import APIRouter, HTTPException
from ...services.pricing_evaluator import evaluate_pricing_model

router = APIRouter(prefix="/evaluate")


@router.post("/pricing-ml")
def evaluate_pricing():
    try:
        return evaluate_pricing_model()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))