from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.services.scheduler_service import start_scheduler
from app.api.routes.discovery import router as discovery_router

app = FastAPI(title="scraping_service")

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


@app.on_event("startup")
def startup():
    start_scheduler()


app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(discovery_router)