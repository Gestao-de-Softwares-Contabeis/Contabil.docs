from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.document import CoreDocumentResult, CoreProcessingStatus


QUEUE_SENT_STATUS = "ENVIADO"
QUEUE_DISCARDED_STATUS = "DESCARTADO"
QUEUE_SENDING_STATUS = "ENVIANDO"
QUEUE_SEND_ERROR_STATUS = "ERRO_ENVIO"
QUEUE_PENDING_EXCLUDED_STATUSES = {QUEUE_SENT_STATUS, QUEUE_DISCARDED_STATUS}


class DocumentQueueItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    file_hash: str
    original_file_name: str | None = None
    extension: str | None = None
    storage_path: str | None = None
    signed_url: str | None = None
    uploaded_by: str | None = None
    source_channel: str | None = None
    client_code: str | None = None
    client_name: str | None = None
    client_cnpj: str | None = None
    competence: str | None = None
    document_type: str | None = None
    institution: str | None = None
    confidence: float | None = None
    status: str | None = None
    review_reason: str | None = None
    destination_folder_id: str | None = None
    destination_path_readable: str | None = None
    new_file_name: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data["payload_json"] = data.get("payload_json") or {}
        return data

    def to_core_result(self) -> CoreDocumentResult:
        payload = dict(self.payload_json or {})
        result_payload = payload.get("core_result") if isinstance(payload.get("core_result"), dict) else payload

        if result_payload:
            result = CoreDocumentResult.model_validate(result_payload)
        else:
            result = CoreDocumentResult(
                original_file_name=self.original_file_name or "",
                extension=self.extension or "",
                detected_client_code=self.client_code,
                detected_client_name=self.client_name,
                detected_client_cnpj=self.client_cnpj,
                competence=self.competence,
                document_type=self.document_type or "documento_diverso",
                institution=self.institution,
                confidence=float(self.confidence or 0),
                status=self._core_status(),
                destination_folder_id=self.destination_folder_id,
                destination_path_readable=self.destination_path_readable,
                new_file_name=self.new_file_name,
                review_reason=self.review_reason,
                extracted_summary={"file_hash": self.file_hash},
            )

        if self.storage_path:
            storage_upload = dict(result.storage_upload or {})
            storage_upload["storage_path"] = self.storage_path
            if self.signed_url:
                storage_upload["signed_url"] = self.signed_url
            storage_upload.setdefault("bucket", payload.get("bucket") or "incoming-documents")
            storage_upload.setdefault("upload_ok", True)
            storage_upload.setdefault("tamanho", 0)
            storage_upload.setdefault("signed_url_ttl_seconds", 600)
            result.storage_upload = storage_upload
            result.extracted_summary["storage_upload"] = storage_upload

        result.extracted_summary.setdefault("file_hash", self.file_hash)
        return result

    def _core_status(self) -> CoreProcessingStatus:
        if self.status == CoreProcessingStatus.READY_TO_SEND.value:
            return CoreProcessingStatus.READY_TO_SEND
        if self.status == CoreProcessingStatus.REVIEW.value:
            return CoreProcessingStatus.REVIEW
        return CoreProcessingStatus.IDENTIFICATION_ERROR
