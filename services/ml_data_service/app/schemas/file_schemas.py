from pydantic import BaseModel
from typing import List


class FileListItem(BaseModel):
    filename: str
    absolute_path: str


class FileListResponse(BaseModel):
    dataset_id: str
    files: List[FileListItem]