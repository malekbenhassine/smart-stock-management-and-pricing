from pathlib import Path
import joblib

MODEL = None
FEATURES = None
USE_LOG = False


def load_model():
    global MODEL, FEATURES, USE_LOG

    base_dir = Path(__file__).resolve().parent
    model_path = base_dir / "models" / "demand_model.pkl"
    features_path = base_dir / "models" / "demand_features.pkl"
    log_transform_path = base_dir / "models" / "use_log_transform.pkl"

    if not model_path.exists():
        raise FileNotFoundError(f"Modèle introuvable : {model_path}")

    MODEL = joblib.load(model_path)

    FEATURES = joblib.load(features_path) if features_path.exists() else None
    USE_LOG = bool(joblib.load(log_transform_path)) if log_transform_path.exists() else False


def get_model():
    if MODEL is None:
        load_model()
    return MODEL, FEATURES, USE_LOG