from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import alerts, health
from app.core.config import get_settings
from app.core.database import Base, engine
from app.models.alert import Alert  # noqa: F401
from app.models.alert_rule import AlertRule  # noqa: F401

settings = get_settings()

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(alerts.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {"service": settings.APP_NAME, "status": "running"}
