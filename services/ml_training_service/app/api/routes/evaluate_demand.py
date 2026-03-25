from fastapi import APIRouter, HTTPException
import pandas as pd

from ...core.config import DATA_DIR
from ...services.demand_evaluator import evaluate_demand_model

router = APIRouter(prefix="/evaluate")


@router.post("/demand-ml")
def evaluate_demand_ml():
    try:
        sales = pd.read_csv(DATA_DIR / "sales.csv")
        return evaluate_demand_model(sales)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))