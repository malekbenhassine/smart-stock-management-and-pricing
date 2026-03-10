from fastapi import FastAPI
from .api.routes.health import router as health_router
from .api.routes.train import router as train_router
from .api.routes.train_demand import router as train_demand_ml_router
from .api.routes.train_price import router as train_price_router
from .api.routes.train_anomaly import router as train_anomaly_router
from .api.routes.train_promo import router as train_promo_router


app = FastAPI(title="ml-training-service")
app.include_router(health_router)
app.include_router(train_router)
app.include_router(train_demand_ml_router)
app.include_router(train_price_router)
app.include_router(train_anomaly_router)
app.include_router(train_promo_router)