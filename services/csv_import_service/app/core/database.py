import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ─── connexion au container smart_postgres ───────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "smart_postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "smartdb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = SessionLocal = None  # initialisés par init_db()


def init_db():
    global engine, SessionLocal
    from ..models.tables import Base

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    # Crée toutes les tables si elles n'existent pas
    Base.metadata.create_all(bind=engine)
    print(f"[DB] Connecté à {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("[DB] Tables créées / vérifiées.")


def get_db():
    """Dependency FastAPI pour injecter une session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
