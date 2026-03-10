from pathlib import Path
from joblib import load
import re

def latest_artifact(models_dir: Path, prefix: str) -> Path:
    # ex: prefix="demand_weekly_"
    files = sorted(models_dir.glob(f"{prefix}*.joblib"))
    if not files:
        raise FileNotFoundError(f"Aucun artefact trouvé pour prefix={prefix} dans {models_dir}")
    return files[-1]

class ModelStore:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._cache = {}

    def load_latest(self, key: str, prefix: str):
        path = latest_artifact(self.models_dir, prefix)
        cached = self._cache.get(key)
        if cached and cached.get("path") == str(path):
            return cached["obj"]
        obj = load(path)
        self._cache[key] = {"path": str(path), "obj": obj}
        return obj