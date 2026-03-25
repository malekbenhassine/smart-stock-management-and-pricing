from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...services.dataset_service import DatasetService
from ...schemas.file_schemas import FileListResponse

router = APIRouter(prefix="/files", tags=["files"])
service = DatasetService()


@router.get("/{dataset_id}", response_model=FileListResponse)
def list_dataset_files(dataset_id: str):
    try:
        files = service.list_files(dataset_id)
        return {
            "dataset_id": dataset_id,
            "files": files
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur listing fichiers: {exc}") from exc


@router.get("/{dataset_id}/{filename:path}")
def download_dataset_file(dataset_id: str, filename: str):
    try:
        path = service.get_file_path(dataset_id, filename)
        return FileResponse(path=str(path), filename=path.name, media_type="text/csv")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur téléchargement fichier: {exc}") from exc