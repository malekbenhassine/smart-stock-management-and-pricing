from pathlib import Path
from datetime import datetime
from typing import List
from fastapi import UploadFile

from ..core.config import UPLOADS_DIR
from .storage_service import StorageService
from .csv_validator import validate_csv_file, CsvValidationError, REQUIRED_FILES


class DatasetService:
    def __init__(self):
        self.storage = StorageService(UPLOADS_DIR)

    async def import_dataset(self, files: List[UploadFile], field_names: List[str]) -> dict:
        if not files:
            raise ValueError("Aucun fichier reçu dans la requête.")

        dataset_dir = self.storage.create_dataset_dir()
        warnings: list[str] = []
        file_summaries: list[dict] = []

        try:
            uploaded_names = set()

            for idx, file in enumerate(files):
                filename = (file.filename or "").strip()

                if not filename:
                    raise ValueError("Un fichier reçu n'a pas de nom.")

                if filename in uploaded_names:
                    raise ValueError(f"Le fichier {filename} est envoyé en double.")
                uploaded_names.add(filename)

                content = await file.read()
                if not content:
                    raise ValueError(f"Le fichier {filename} est vide.")

                saved_path = self.storage.save_bytes(dataset_dir, filename, content)
                summary = validate_csv_file(saved_path, filename)
                summary["field_name"] = field_names[idx] if idx < len(field_names) else "files"
                file_summaries.append(summary)

            missing_required = sorted(REQUIRED_FILES - uploaded_names)
            if missing_required:
                raise ValueError(
                    f"Fichiers obligatoires manquants: {missing_required}. "
                    f"Minimum requis: {sorted(REQUIRED_FILES)}"
                )

            manifest = {
                "dataset_id": dataset_dir.name,
                "status": "READY",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "dataset_dir": str(dataset_dir),
                "files": file_summaries,
                "warnings": warnings,
            }

            self.storage.write_manifest(dataset_dir, manifest)
            return manifest

        except Exception:
            self.storage.delete_dataset_dir(dataset_dir)
            raise

    def list_datasets(self) -> list[dict]:
        datasets = []
        for dataset_dir in self.storage.list_dataset_dirs():
            try:
                manifest = self.storage.read_manifest(dataset_dir)
            except Exception:
                manifest = {
                    "dataset_id": dataset_dir.name,
                    "status": "UNKNOWN",
                    "created_at": "",
                    "dataset_dir": str(dataset_dir),
                    "files": [],
                    "warnings": ["manifest.json manquant ou illisible"],
                }
            datasets.append(manifest)
        return datasets

    def get_dataset(self, dataset_id: str) -> dict:
        dataset_dir = UPLOADS_DIR / dataset_id
        if not dataset_dir.exists() or not dataset_dir.is_dir():
            raise FileNotFoundError(f"Dataset introuvable: {dataset_id}")
        return self.storage.read_manifest(dataset_dir)

    def list_files(self, dataset_id: str) -> list[dict]:
        dataset_dir = UPLOADS_DIR / dataset_id
        if not dataset_dir.exists() or not dataset_dir.is_dir():
            raise FileNotFoundError(f"Dataset introuvable: {dataset_id}")

        files = []
        for path in sorted(dataset_dir.iterdir()):
            if path.is_file() and path.name != "manifest.json":
                files.append({
                    "filename": path.name,
                    "absolute_path": str(path.resolve()),
                })
        return files

    def get_file_path(self, dataset_id: str, filename: str) -> Path:
        dataset_dir = UPLOADS_DIR / dataset_id
        if not dataset_dir.exists() or not dataset_dir.is_dir():
            raise FileNotFoundError(f"Dataset introuvable: {dataset_id}")

        target = (dataset_dir / filename).resolve()
        if dataset_dir.resolve() not in target.parents and target != dataset_dir.resolve():
            raise FileNotFoundError("Chemin invalide.")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"Fichier introuvable: {filename}")

        return target

    def activate_dataset(self, dataset_id: str) -> dict:
        dataset_dir = UPLOADS_DIR / dataset_id
        if not dataset_dir.exists() or not dataset_dir.is_dir():
            raise FileNotFoundError(f"Dataset introuvable: {dataset_id}")

        self.storage.set_active_dataset(dataset_id)
        return {
            "dataset_id": dataset_id,
            "active_dataset_id": dataset_id,
            "status": "ACTIVE",
        }

    def get_active_dataset(self) -> dict:
        return {
            "active_dataset_id": self.storage.get_active_dataset()
        }