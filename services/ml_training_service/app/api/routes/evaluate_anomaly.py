from fastapi import APIRouter, HTTPException
from ...services.anomaly_evaluator import evaluate_anomaly_model

router = APIRouter(prefix="/evaluate")

@router.post("/anomaly-ml")
def evaluate_anomaly():
    try:
        return evaluate_anomaly_model()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))