from pathlib import Path
from datetime import datetime
import json
import shutil
from typing import List


class StorageService:
    def __init__(self, uploads_dir: Path):
        self.uploads_dir = uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def create_dataset_dir(self) -> Path:
        dataset_id = f"dataset_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
        dataset_dir = self.uploads_dir / dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=False)
        return dataset_dir

    def save_bytes(self, dataset_dir: Path, filename: str, content: bytes) -> Path:
        path = dataset_dir / filename
        path.write_bytes(content)
        return path

    def write_manifest(self, dataset_dir: Path, manifest: dict) -> None:
        manifest_path = dataset_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def read_manifest(self, dataset_dir: Path) -> dict:
        manifest_path = dataset_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json introuvable dans {dataset_dir}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def delete_dataset_dir(self, dataset_dir: Path) -> None:
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir, ignore_errors=True)

    def list_dataset_dirs(self) -> List[Path]:
        if not self.uploads_dir.exists():
            return []
        return sorted(
            [p for p in self.uploads_dir.iterdir() if p.is_dir() and p.name.startswith("dataset_")],
            key=lambda p: p.name,
            reverse=True,
        )

    def set_active_dataset(self, dataset_id: str) -> None:
        active_file = self.uploads_dir / "active_dataset.txt"
        active_file.write_text(dataset_id, encoding="utf-8")

    def get_active_dataset(self) -> str | None:
        active_file = self.uploads_dir / "active_dataset.txt"
        if not active_file.exists():
            return None
        value = active_file.read_text(encoding="utf-8").strip()
        return value or None