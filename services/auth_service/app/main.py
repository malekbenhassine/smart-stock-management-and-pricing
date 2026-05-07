from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.journal_authentification import router as journal_authentification_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.database import Base, engine

from app.models.user import User
from app.models.activation_token import ActivationToken
from app.models.password_reset_token import PasswordResetToken
from app.models.journal_authentification import JournalAuthentification

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(journal_authentification_router)