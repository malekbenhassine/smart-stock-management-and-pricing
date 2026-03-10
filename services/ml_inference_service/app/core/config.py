from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[4]

load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).resolve()
MODELS_DIR = Path(os.getenv("MODELS_DIR", BASE_DIR / "services/ml_inference_service/artifacts/models")).resolve()
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", BASE_DIR / "services/ml_inference_service/artifacts/reports")).resolve()

DATA_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)