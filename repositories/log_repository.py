from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from database.supabase_client import get_supabase_client
from models.document import DocumentLogEntry
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class ProcessingLogRepository:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def insert(self, entry: DocumentLogEntry) -> DocumentLogEntry:
        payload = self._to_db_payload(entry)
        try:
            response = self.client.table("document_processing_log").insert(payload).execute()
            rows: list[dict[str, Any]] = response.data or [payload]
            return self._from_db_row(rows[0])
        except Exception as exc:
            logger.exception(
                "Erro ao inserir log",
                extra={"ctx_action": entry.action, "ctx_file_hash": entry.file_hash},
            )
            self._raise_schema_error_if_needed(exc)
            raise

    def list_logs(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        client_id: str | None = None,
        user_name: str | None = None,
        user_department: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[DocumentLogEntry]:
        try:
            query = self.client.table("document_processing_log").select("*")
            if start_date:
                start = datetime.combine(start_date, time.min).isoformat()
                query = query.gte("processed_at", start)
            if end_date:
                end = datetime.combine(end_date, time.max).isoformat()
                query = query.lte("processed_at", end)
            if client_id:
                query = query.eq("client_code", client_id)
            if user_name:
                query = query.eq("uploaded_by", user_name)
            if status:
                query = query.eq("status", status)

            response = query.order("processed_at", desc=True).limit(limit).execute()
            logs = [self._from_db_row(row) for row in response.data or []]
            if user_department:
                logs = [log for log in logs if log.user_department == user_department]
            return logs
        except Exception as exc:
            logger.exception("Erro ao listar historico")
            self._raise_schema_error_if_needed(exc)
            raise

    def list_current_documents(self, limit: int = 1000) -> list[DocumentLogEntry]:
        logs = self.list_logs(limit=limit)
        latest_by_hash: dict[str, DocumentLogEntry] = {}
        for item in logs:
            key = item.file_hash or item.id or ""
            if key and key not in latest_by_hash:
                latest_by_hash[key] = item
        return list(latest_by_hash.values())

    def _raise_schema_error_if_needed(self, exc: Exception) -> None:
        message = str(exc)
        schema_markers = [
            "PGRST204",
            "schema cache",
            "column document_processing_log",
            "Could not find the",
        ]
        if any(marker in message for marker in schema_markers):
            raise RuntimeError(
                "Schema do Supabase desatualizado. Rode o arquivo "
                "database/repair_existing_schema.sql no SQL Editor do Supabase e recarregue o app."
            ) from exc

    def _to_db_payload(self, entry: DocumentLogEntry) -> dict[str, Any]:
        raw_entry = entry.model_dump(mode="json", exclude_none=True)
        metadata = dict(entry.metadata or {})
        confidence = None
        if entry.score is not None:
            confidence = float(entry.score)
            if confidence > 1:
                confidence = confidence / 100

        payload: dict[str, Any] = {
            "uploaded_by": entry.user_name,
            "source_channel": entry.origin_channel,
            "original_file_name": entry.original_filename,
            "extension": entry.file_extension,
            "new_file_name": metadata.get("new_file_name"),
            "client_code": metadata.get("client_code") or entry.client_id,
            "client_name": entry.client_name,
            "client_cnpj": metadata.get("client_cnpj"),
            "competence": entry.competence,
            "document_type": entry.document_type,
            "institution": entry.institution,
            "confidence": confidence,
            "status": entry.status,
            "message": self._message(entry),
            "destination_folder_id": metadata.get("destination_folder_id") or entry.destination_folder,
            "destination_path_readable": metadata.get("destination_path_readable") or entry.destination_folder,
            "payload_json": raw_entry,
        }
        if entry.created_at:
            payload["processed_at"] = entry.created_at.isoformat()
        return {key: value for key, value in payload.items() if value is not None}

    def _from_db_row(self, row: dict[str, Any]) -> DocumentLogEntry:
        metadata = dict(row.get("payload_json") or {})
        confidence = row.get("confidence")
        score = metadata.get("score")
        if score is None and confidence is not None:
            score = int(float(confidence) * 100)

        return DocumentLogEntry(
            id=row.get("id"),
            created_at=row.get("processed_at"),
            user_name=metadata.get("user_name") or row.get("uploaded_by") or "sistema",
            user_department=metadata.get("user_department"),
            action=metadata.get("action") or row.get("message") or "LOG",
            client_id=metadata.get("client_id") or row.get("client_code"),
            client_name=row.get("client_name") or metadata.get("client_name"),
            original_filename=row.get("original_file_name"),
            file_extension=row.get("extension"),
            file_size_bytes=metadata.get("file_size_bytes"),
            file_hash=metadata.get("file_hash"),
            competence=row.get("competence"),
            document_type=row.get("document_type"),
            institution=row.get("institution"),
            score=score,
            score_band=metadata.get("score_band"),
            matched_by=metadata.get("matched_by"),
            ai_used=metadata.get("ai_used"),
            sender_name=metadata.get("sender_name") or row.get("uploaded_by"),
            sender_department=metadata.get("sender_department"),
            origin_channel=row.get("source_channel") or metadata.get("origin_channel"),
            status=row.get("status") or metadata.get("status") or "",
            destination_folder=row.get("destination_folder_id") or metadata.get("destination_folder"),
            extracted_text=metadata.get("extracted_text"),
            observation=metadata.get("observation") or row.get("message"),
            metadata=metadata.get("metadata") or metadata,
        )

    def _message(self, entry: DocumentLogEntry) -> str:
        if entry.observation:
            return f"{entry.action}: {entry.observation}"
        return entry.action
