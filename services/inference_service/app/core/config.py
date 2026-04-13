import os
from pathlib import Path

DB_HOST = os.getenv("DB_HOST", "postgres_inference")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "inference_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

MODELS_DIR = Path(os.getenv("MODELS_DIR", "models"))
MODEL_PATH = MODELS_DIR / "demand_model.pkl"
FEATURES_PATH = MODELS_DIR / "demand_features.pkl"
LOG_TRANSFORM_PATH = MODELS_DIR / "use_log_transform.pkl"

RESTOCK_THRESHOLD = float(os.getenv("RESTOCK_THRESHOLD", "1.5"))
RESTOCK_MULTIPLIER = float(os.getenv("RESTOCK_MULTIPLIER", "3.0"))
MIN_MARGIN_RATIO = float(os.getenv("MIN_MARGIN_RATIO", "0.30"))
MAX_PRICE_CHANGE = float(os.getenv("MAX_PRICE_CHANGE", "0.20"))