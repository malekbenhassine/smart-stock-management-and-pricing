from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.database import init_db
from .api.routes.csv_import import router as import_router

app = FastAPI(
    title="CSV Import Service",
    description="Upload des fichiers CSV → PostgreSQL (smart_postgres) + déclenchement ML",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


app.include_router(import_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "csv_import_service"}
#nrmlmt fi routes 