from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile as StarletteUploadFile

from ...services.dataset_service import DatasetService
from ...services.csv_validator import CsvValidationError
from ...schemas.dataset_schemas import (
    DatasetManifestResponse,
    DatasetActivateResponse,
    ActiveDatasetResponse,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])
service = DatasetService()


@router.post("/import", response_model=DatasetManifestResponse)
async def import_dataset(request: Request):
    try:
        form = await request.form()

        files = []
        field_names = []

        for field_name, value in form.multi_items():
            if isinstance(value, StarletteUploadFile):
                files.append(value)
                field_names.append(field_name)

        if not files:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Aucun fichier reçu. "
                    "Envoie les CSV en multipart/form-data. "
                    "Tu peux utiliser des champs nommés (sales, products, ...) ou files."
                ),
            )

        return await service.import_dataset(files, field_names)

    except CsvValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur import dataset: {exc}") from exc


@router.get("", response_model=list[DatasetManifestResponse])
def list_datasets():
    try:
        return service.list_datasets()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur listing datasets: {exc}") from exc


@router.get("/active", response_model=ActiveDatasetResponse)
def get_active_dataset():
    try:
        return service.get_active_dataset()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur lecture dataset actif: {exc}") from exc


@router.post("/{dataset_id}/activate", response_model=DatasetActivateResponse)
def activate_dataset(dataset_id: str):
    try:
        return service.activate_dataset(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur activation dataset: {exc}") from exc


@router.get("/{dataset_id}", response_model=DatasetManifestResponse)
def get_dataset(dataset_id: str):
    try:
        return service.get_dataset(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur lecture dataset: {exc}") from exc