from fastapi import APIRouter, HTTPException
from ...services.restock_evaluator import evaluate_restock_model

router = APIRouter(prefix="/evaluate")


@router.post("/restock-ml")
def evaluate_restock():
    try:
        return evaluate_restock_model()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))