from pydantic import BaseModel
from typing import List, Optional


class DatasetFileSummary(BaseModel):
    field_name: str
    filename: str
    rows: int
    columns: List[str]
    required_columns: List[str]
    missing_columns: List[str]
    status: str


class DatasetManifestResponse(BaseModel):
    dataset_id: str
    status: str
    created_at: str
    dataset_dir: str
    files: List[DatasetFileSummary]
    warnings: List[str] = []


class DatasetActivateResponse(BaseModel):
    dataset_id: str
    active_dataset_id: str
    status: str


class ActiveDatasetResponse(BaseModel):
    active_dataset_id: Optional[str] = None