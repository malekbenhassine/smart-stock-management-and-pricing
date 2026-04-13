from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.database import engine, Base
from app.api.routes.health import router as health_router
from app.api.routes.predict_demand import router as demand_router
from app.api.routes.recommend_price import router as price_router
from app.api.routes.recommend_restock import router as restock_router
from app.api.routes.recommend_promo import router as promo_router
from app.api.routes.predict_stock_risk import router as stock_risk_router
from app.api.routes.detect_anomalies import router as anomalies_router
from app.api.routes.dashboard_recommendations import router as dashboard_router
from app.api.routes.history_route import router as history_router
from app.api.routes.stock_details_route import router as stock_details_router
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Démarrage du inference_service...")
    Base.metadata.create_all(bind=engine)

    from app.model_loader import load_model
    load_model()

    logger.info("Modèle chargé")
    yield
    logger.info("Arrêt du inference_service")


app = FastAPI(
    title="inference_service",
    lifespan=lifespan,
)

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
app.include_router(promo_router)
app.include_router(stock_risk_router)
app.include_router(anomalies_router)
app.include_router(dashboard_router)
app.include_router(history_router)
app.include_router(stock_details_router)