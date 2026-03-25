from pydantic import BaseModel
from typing import Literal

RiskLabel = Literal["STOCKOUT", "OVERSTOCK", "OVERSTOCK_CRITIQUE", "OK"]


class StockRiskInputs(BaseModel):
    current_stock: int
    threshold_min: int
    threshold_max: int
    demand_weekly_p50: float
    demand_weekly_p90: float
    lead_time_days: int


class StockRiskResponse(BaseModel):
    product_id: int
    risk: RiskLabel
    probability: float
    inputs: StockRiskInputs
    explanation: str