from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.supabase_client import get_supabase_client
from models.document import CoreDocumentResult
from models.document_queue import DocumentQueueItem, QUEUE_DISCARDED_STATUS, QUEUE_PENDING_EXCLUDED_STATUSES, QUEUE_SENT_STATUS
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class DocumentQueueRepository:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def upsert_document_queue(
        self,
        result: CoreDocumentResult,
        uploaded_by: str | None = None,
        source_channel: str | None = None,
    ) -> tuple[DocumentQueueItem, bool]:
        file_hash = self._result_file_hash(result)
        if not file_hash:
            raise ValueError("Nao foi possivel salvar na fila: hash do arquivo ausente.")

        payload = self._to_db_payload(
            result=result,
            uploaded_by=uploaded_by,
            source_channel=source_channel,
            file_hash=file_hash,
        )
        existing = self._find_active_by_hash(file_hash)
        try:
            if existing:
                merged = self._merge_existing_storage(payload, existing)
                response = (
                    self.client.table("document_queue")
                    .update(merged)
                    .eq("id", existing.id)
                    .execute()
                )
                return self._first_row(response.data, merged), False

            response = self.client.table("document_queue").insert(payload).execute()
            return self._first_row(response.data, payload), True
        except Exception:
            logger.exception(
                "Erro ao salvar documento na fila",
                extra={"ctx_file": result.original_file_name, "ctx_file_hash": file_hash},
            )
            raise

    def list_pending_documents(self, limit: int = 500) -> list[DocumentQueueItem]:
        try:
            response = (
                self.client.table("document_queue")
                .select("*")
                .neq("status", QUEUE_SENT_STATUS)
                .neq("status", QUEUE_DISCARDED_STATUS)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return [DocumentQueueItem.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar fila de documentos")
            raise

    def list_sent_documents(
        self,
        client_code: str,
        competences: list[str],
        limit: int = 5000,
    ) -> list[DocumentQueueItem]:
        if not competences:
            return []
        try:
            response = (
                self.client.table("document_queue")
                .select("*")
                .eq("client_code", client_code)
                .eq("status", QUEUE_SENT_STATUS)
                .in_("competence", competences)
                .limit(limit)
                .execute()
            )
            return [DocumentQueueItem.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar documentos enviados", extra={"ctx_client_code": client_code})
            raise

    def get_by_id(self, item_id: str) -> DocumentQueueItem | None:
        try:
            response = (
                self.client.table("document_queue")
                .select("*")
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
            rows: list[dict[str, Any]] = response.data or []
            return DocumentQueueItem.model_validate(rows[0]) if rows else None
        except Exception:
            logger.exception("Erro ao buscar documento na fila", extra={"ctx_queue_id": item_id})
            raise

    def update_document_status(
        self,
        item_id: str,
        status: str,
        message: str | None = None,
    ) -> DocumentQueueItem:
        payload: dict[str, Any] = {"status": status, "updated_at": self._now()}
        if message:
            payload["review_reason"] = message
        return self._update_item(item_id, payload)

    def update_storage_url(self, item_id: str, signed_url: str) -> DocumentQueueItem:
        return self._update_item(item_id, {"signed_url": signed_url, "updated_at": self._now()})

    def mark_as_sent(self, item_id: str, result: CoreDocumentResult) -> DocumentQueueItem:
        existing = self.get_by_id(item_id)
        payload = self._to_db_payload(
            result=result,
            uploaded_by=existing.uploaded_by if existing else None,
            source_channel=existing.source_channel if existing else None,
            file_hash=self._result_file_hash(result),
            status=QUEUE_SENT_STATUS,
        )
        payload["sent_at"] = self._now()
        payload["updated_at"] = self._now()
        self._update_item(item_id, payload)
        refreshed = self.get_by_id(item_id)
        if not refreshed:
            raise RuntimeError(f"Documento da fila nao encontrado apos marcar ENVIADO: {item_id}")
        return refreshed

    def mark_as_error(
        self,
        item_id: str,
        message: str,
        result: CoreDocumentResult | None = None,
    ) -> DocumentQueueItem:
        payload: dict[str, Any] = {
            "status": "ERRO_ENVIO",
            "review_reason": message,
            "updated_at": self._now(),
        }
        if result:
            payload.update(
                self._to_db_payload(
                    result=result,
                    uploaded_by=None,
                    source_channel=None,
                    file_hash=self._result_file_hash(result),
                    status="ERRO_ENVIO",
                )
            )
            payload["review_reason"] = message
        return self._update_item(item_id, payload)

    def discard_document(self, item_id: str, message: str | None = None) -> DocumentQueueItem:
        return self.update_document_status(item_id, QUEUE_DISCARDED_STATUS, message or "Documento descartado pelo usuario.")

    def _find_active_by_hash(self, file_hash: str) -> DocumentQueueItem | None:
        response = (
            self.client.table("document_queue")
            .select("*")
            .eq("file_hash", file_hash)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        for row in response.data or []:
            item = DocumentQueueItem.model_validate(row)
            if item.status not in QUEUE_PENDING_EXCLUDED_STATUSES:
                return item
        return None

    def _update_item(self, item_id: str, payload: dict[str, Any]) -> DocumentQueueItem:
        try:
            response = self.client.table("document_queue").update(payload).eq("id", item_id).execute()
            rows: list[dict[str, Any]] = response.data or []
            if rows:
                return DocumentQueueItem.model_validate(rows[0])
            item = self.get_by_id(item_id)
            if not item:
                raise RuntimeError(f"Documento da fila nao encontrado apos update: {item_id}")
            return item
        except Exception:
            logger.exception("Erro ao atualizar fila de documentos", extra={"ctx_queue_id": item_id})
            raise

    def _first_row(self, rows: list[dict[str, Any]] | None, fallback: dict[str, Any]) -> DocumentQueueItem:
        return DocumentQueueItem.model_validate((rows or [fallback])[0])

    def _result_file_hash(self, result: CoreDocumentResult) -> str:
        return str(result.extracted_summary.get("file_hash") or "").strip()

    def _to_db_payload(
        self,
        result: CoreDocumentResult,
        uploaded_by: str | None,
        source_channel: str | None,
        file_hash: str,
        status: str | None = None,
    ) -> dict[str, Any]:
        storage_upload = dict(result.storage_upload or {})
        payload_json = result.model_dump(mode="json", exclude_none=True)
        payload_json["core_result"] = payload_json.copy()

        payload: dict[str, Any] = {
            "file_hash": file_hash,
            "original_file_name": result.original_file_name,
            "extension": result.extension,
            "storage_path": storage_upload.get("storage_path"),
            "signed_url": storage_upload.get("signed_url"),
            "uploaded_by": uploaded_by,
            "source_channel": source_channel,
            "client_code": result.detected_client_code,
            "client_name": result.detected_client_name,
            "client_cnpj": result.detected_client_cnpj,
            "competence": result.competence,
            "document_type": result.document_type,
            "institution": result.institution,
            "confidence": result.confidence,
            "status": status or result.status.value,
            "review_reason": result.review_reason,
            "destination_folder_id": result.destination_folder_id,
            "destination_path_readable": result.destination_path_readable,
            "new_file_name": result.new_file_name,
            "payload_json": payload_json,
            "updated_at": self._now(),
        }
        return {key: value for key, value in payload.items() if value is not None}

    def _merge_existing_storage(
        self,
        payload: dict[str, Any],
        existing: DocumentQueueItem,
    ) -> dict[str, Any]:
        if "storage_path" not in payload and existing.storage_path:
            payload["storage_path"] = existing.storage_path
        if "signed_url" not in payload and existing.signed_url:
            payload["signed_url"] = existing.signed_url
        if "uploaded_by" not in payload and existing.uploaded_by:
            payload["uploaded_by"] = existing.uploaded_by
        if "source_channel" not in payload and existing.source_channel:
            payload["source_channel"] = existing.source_channel
        return payload

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
