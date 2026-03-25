from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes.health import router as health_router
from .api.routes.predict_demand import router as demand_router
from .api.routes.recommend_price import router as price_router
from .api.routes.recommend_restock import router as restock_router
from .api.routes.detect_anomalies import router as anomaly_router
from .api.routes.predict_stock_risk import router as stock_risk_router
from .api.routes.recommend_promo import router as promo_router

app = FastAPI(title="ml-inference-service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(demand_router)
app.include_router(price_router)
app.include_router(restock_router)
app.include_router(anomaly_router)
app.include_router(stock_risk_router)
app.include_router(promo_router)