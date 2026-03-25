from pathlib import Path
from ..core.config import DATA_DIR


def resolve_data_dir(dataset_id: str | None = None) -> Path:
    if not dataset_id:
        return DATA_DIR

    dataset_dir = (DATA_DIR / "uploads" / dataset_id).resolve()
    if not dataset_dir.exists() or not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset introuvable: {dataset_id}")

    return dataset_dir