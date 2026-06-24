from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StorageUploadResult(BaseModel):
    upload_ok: bool
    bucket: str
    storage_path: str
    tamanho: int
    signed_url: str
    signed_url_ttl_seconds: int
    response_path: str | None = None


class N8NDispatchResult(BaseModel):
    send_ok: bool
    skipped: bool = False
    bucket: str | None = None
    storage_path: str | None = None
    new_file_name: str | None = None
    destination_folder_id: str | None = None
    signed_url: str | None = None
    n8n_status_code: int | None = None
    n8n_response_body: str | None = None
    error: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
