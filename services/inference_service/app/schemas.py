# inference_service / schemas.py
from pydantic import BaseModel, Field
from typing import Optional
import datetime

class BaseRequest(BaseModel):
    store_id: str = Field(..., example="S001")
    product_id: str = Field(..., example="P0001")
    date: datetime.date = Field(..., example="2024-07-01")

    price: float = Field(..., gt=0, example=43.71)
    stock: float = Field(..., ge=0, example=150.0)

    discount: float = Field(0.0, ge=0, le=100, example=10.0)
    competitor_pricing: Optional[float] = Field(None, example=45.0)
    units_ordered: float = Field(0.0, ge=0, example=0.0)
    weather_condition: Optional[str] = Field(None, example="Sunny")
    category: Optional[str] = Field(None, example="Groceries")
    region: Optional[str] = Field(None, example="North")

    threshold_min: Optional[float] = Field(0.0, example=20)
    threshold_max: Optional[float] = Field(0.0, example=100)
    cost_price: Optional[float] = Field(None, example=25.0)
    min_price: Optional[float] = Field(None, example=30.0)
    brand: Optional[str] = Field(None, example="HP")
    min_margin: Optional[float] = Field(0.0, example=0.2)
    peak_season: Optional[str] = Field(None, example="Summer")
    seasonality_factor: Optional[float] = Field(1.0, example=1.1)
# ── Réponses : Demand ────────────────────────────────────────────────────────
class DemandResponse(BaseModel):
    store_id:         str
    product_id:       str
    date:             datetime.date
    predicted_demand: float   = Field(..., description="Unités prévues")
    confidence_low:   float   = Field(..., description="Borne basse (-15%)")
    confidence_high:  float   = Field(..., description="Borne haute (+15%)")
    history_days_used: int    = Field(..., description="Jours d'historique disponibles")

# ── Réponses : Pricing ───────────────────────────────────────────────────────
class PricingResponse(BaseModel):
    store_id:           str
    product_id:         str
    date:               datetime.date
    current_price:      float
    recommended_price:  float
    price_change_pct:   float  = Field(..., description="Variation % vs prix actuel")
    predicted_demand_at_current_price:    float
    predicted_demand_at_recommended_price: float
    reasoning:          str

# ── Réponses : Restock ───────────────────────────────────────────────────────
class RestockResponse(BaseModel):
    store_id:          str
    product_id:        str
    date:              datetime.date
    current_stock:     float
    predicted_demand:  float
    restock_needed:    bool
    recommended_order_qty: float
    days_of_stock_remaining: float
    urgency:           str   = Field(..., description="low / medium / high / critical")
    reasoning:         str

# ── Schéma pour insérer des ventes historiques ───────────────────────────────
class SalesRecord(BaseModel):
    store_id:           str
    product_id:         str
    date:               datetime.date
    category:           Optional[str]  = None
    region:             Optional[str]  = None
    sales:              float
    price:              float
    stock:              Optional[float] = None
    discount:           Optional[float] = 0.0
    competitor_pricing: Optional[float] = None
    units_ordered:      Optional[float] = 0.0
    weather_condition:  Optional[str]  = None
    holiday_promotion:  Optional[int]  = 0
    seasonality:        Optional[str]  = None

class SalesIngestionResponse(BaseModel):
    inserted: int
    message:  str
