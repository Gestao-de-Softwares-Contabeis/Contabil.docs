from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.supabase_client import get_supabase_client
from models.document_checklist import (
    CHECKLIST_DISPENSED,
    CHECKLIST_PENDING,
    CHECKLIST_RECEIVED,
    ChecklistDashboardItem,
    ClientDocumentChecklist,
    DocumentChecklistStatus,
)
from models.document_queue import DocumentQueueItem
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class DocumentChecklistRepository:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def create_checklist_item(self, item: ClientDocumentChecklist) -> ClientDocumentChecklist:
        duplicate = self.find_duplicate_checklist_item(
            client_code=item.client_code,
            document_type=item.document_type,
            file_extension=item.file_extension,
            institution=item.institution,
            document_name_pattern=item.document_name_pattern,
        )
        if duplicate:
            raise ValueError("Este item já existe no checklist deste cliente.")

        payload = item.model_dump(mode="json", exclude_none=True)
        payload.pop("id", None)
        try:
            response = self.client.table("client_document_checklist").insert(payload).execute()
            return ClientDocumentChecklist.model_validate((response.data or [payload])[0])
        except Exception:
            logger.exception("Erro ao criar item de checklist", extra={"ctx_client_code": item.client_code})
            raise

    def update_checklist_item(
        self,
        item_id: str,
        updates: dict[str, Any],
    ) -> ClientDocumentChecklist:
        current = self.get_checklist_item(item_id)
        if not current:
            raise RuntimeError(f"Item do checklist nao encontrado: {item_id}")

        duplicate = self.find_duplicate_checklist_item(
            client_code=str(updates.get("client_code") or current.client_code),
            document_type=str(updates.get("document_type") or current.document_type),
            file_extension=updates.get("file_extension", current.file_extension),
            institution=updates.get("institution", current.institution),
            document_name_pattern=updates.get("document_name_pattern", current.document_name_pattern),
            exclude_id=item_id,
        )
        if duplicate:
            raise ValueError("Este item já existe no checklist deste cliente.")

        payload = {key: value for key, value in updates.items() if key != "id"}
        payload["updated_at"] = self._now()
        try:
            response = self.client.table("client_document_checklist").update(payload).eq("id", item_id).execute()
            rows: list[dict[str, Any]] = response.data or []
            if rows:
                return ClientDocumentChecklist.model_validate(rows[0])
            refreshed = (
                self.client.table("client_document_checklist")
                .select("*")
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
            refreshed_rows: list[dict[str, Any]] = refreshed.data or []
            if not refreshed_rows:
                raise RuntimeError(f"Item do checklist nao encontrado apos update: {item_id}")
            return ClientDocumentChecklist.model_validate(refreshed_rows[0])
        except Exception:
            logger.exception("Erro ao atualizar item de checklist", extra={"ctx_checklist_id": item_id})
            raise

    def set_checklist_item_active(self, item_id: str, active: bool) -> ClientDocumentChecklist:
        return self.update_checklist_item(item_id, {"is_active": active})

    def has_status_for_checklist(self, checklist_id: str) -> bool:
        try:
            response = (
                self.client.table("document_checklist_status")
                .select("id")
                .eq("checklist_id", checklist_id)
                .limit(1)
                .execute()
            )
            return bool(response.data)
        except Exception:
            logger.exception("Erro ao verificar historico mensal do checklist", extra={"ctx_checklist_id": checklist_id})
            raise

    def delete_checklist_item(self, item_id: str) -> bool:
        try:
            self.client.table("client_document_checklist").delete().eq("id", item_id).execute()
            return True
        except Exception as first_error:
            logger.warning(
                "Delete direto do checklist falhou; desvinculando status mensal antigo para liberar item fixo",
                extra={"ctx_checklist_id": item_id, "ctx_error": str(first_error)},
            )
            try:
                self.client.table("document_checklist_status").update(
                    {"checklist_id": None, "updated_at": self._now()}
                ).eq("checklist_id", item_id).execute()
                self.client.table("client_document_checklist").delete().eq("id", item_id).execute()
                return True
            except Exception:
                logger.exception("Erro ao excluir item fixo do checklist", extra={"ctx_checklist_id": item_id})
                raise

    def get_checklist_item(self, item_id: str) -> ClientDocumentChecklist | None:
        try:
            response = (
                self.client.table("client_document_checklist")
                .select("*")
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
            rows: list[dict[str, Any]] = response.data or []
            return ClientDocumentChecklist.model_validate(rows[0]) if rows else None
        except Exception:
            logger.exception("Erro ao buscar item do checklist", extra={"ctx_checklist_id": item_id})
            raise

    def find_duplicate_checklist_item(
        self,
        client_code: str,
        document_type: str,
        file_extension: str | None,
        institution: str | None,
        document_name_pattern: str | None,
        exclude_id: str | None = None,
    ) -> ClientDocumentChecklist | None:
        items = self.list_checklist(client_code=client_code)
        expected = (
            self._normalized_key(document_type),
            self._normalized_extension(file_extension),
            self._normalized_key(institution),
            self._normalized_key(document_name_pattern),
        )
        for item in items:
            if exclude_id and item.id == exclude_id:
                continue
            current = (
                self._normalized_key(item.document_type),
                self._normalized_extension(item.file_extension),
                self._normalized_key(item.institution),
                self._normalized_key(item.document_name_pattern),
            )
            if current == expected:
                return item
        return None

    def list_checklist(
        self,
        client_code: str | None = None,
        active_only: bool = False,
        limit: int = 1000,
    ) -> list[ClientDocumentChecklist]:
        try:
            query = self.client.table("client_document_checklist").select("*")
            if client_code:
                query = query.eq("client_code", client_code)
            if active_only:
                query = query.eq("is_active", True)
            response = query.order("created_at", desc=True).limit(limit).execute()
            return [ClientDocumentChecklist.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar checklist", extra={"ctx_client_code": client_code})
            raise

    def list_active_for_client(self, client_code: str) -> list[ClientDocumentChecklist]:
        return self.list_checklist(client_code=client_code, active_only=True)

    def ensure_monthly_statuses(
        self,
        client_code: str,
        competence: str,
    ) -> list[DocumentChecklistStatus]:
        statuses: list[DocumentChecklistStatus] = []
        for checklist_item in self.list_active_for_client(client_code):
            existing = self.get_status(checklist_item.id, client_code, competence)
            if existing:
                statuses.append(existing)
                continue
            statuses.append(
                self.create_status(
                    checklist_item=checklist_item,
                    competence=competence,
                    status=CHECKLIST_PENDING,
                    auto_matched=False,
                )
            )
        return statuses

    def list_statuses(
        self,
        client_code: str | None = None,
        competence: str | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[DocumentChecklistStatus]:
        try:
            query = self.client.table("document_checklist_status").select("*")
            if client_code:
                query = query.eq("client_code", client_code)
            if competence:
                query = query.eq("competence", competence)
            if status and status != "Todos":
                query = query.eq("status", status)
            response = query.order("created_at", desc=True).limit(limit).execute()
            return [DocumentChecklistStatus.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar status do checklist")
            raise

    def list_statuses_for_competences(
        self,
        client_code: str,
        competences: list[str],
        limit: int = 5000,
    ) -> list[DocumentChecklistStatus]:
        if not competences:
            return []
        try:
            response = (
                self.client.table("document_checklist_status")
                .select("*")
                .eq("client_code", client_code)
                .in_("competence", competences)
                .limit(limit)
                .execute()
            )
            return [DocumentChecklistStatus.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar status do checklist por periodo", extra={"ctx_client_code": client_code})
            raise

    def list_dashboard(self, client_code: str | None = None, competence: str | None = None) -> list[ChecklistDashboardItem]:
        try:
            query = self.client.table("checklist_dashboard").select("*")
            if client_code:
                query = query.eq("client_code", client_code)
            if competence:
                query = query.eq("competence", competence)
            response = query.execute()
            return [ChecklistDashboardItem.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar dashboard do checklist")
            raise

    def mark_received(
        self,
        checklist_item: ClientDocumentChecklist,
        queue_item: DocumentQueueItem,
    ) -> DocumentChecklistStatus:
        if not queue_item.competence:
            raise ValueError("Documento sem competencia nao pode marcar checklist.")
        existing = self.get_status(checklist_item.id, queue_item.client_code or checklist_item.client_code, queue_item.competence)
        payload = {
            "checklist_id": checklist_item.id,
            "client_code": queue_item.client_code or checklist_item.client_code,
            "competence": queue_item.competence,
            "document_type": queue_item.document_type or checklist_item.document_type,
            "file_extension": queue_item.extension,
            "institution": queue_item.institution,
            "status": CHECKLIST_RECEIVED,
            "matched_document_queue_id": queue_item.id,
            "uploaded_by": queue_item.uploaded_by,
            "auto_matched": True,
            "received_at": self._now(),
            "updated_at": self._now(),
        }
        if existing and existing.id:
            return self.update_status(existing.id, payload)
        return self.create_status_from_payload(payload)

    def set_status(
        self,
        status_id: str,
        status: str,
        auto_matched: bool = False,
    ) -> DocumentChecklistStatus:
        payload: dict[str, Any] = {
            "status": status,
            "auto_matched": auto_matched,
            "updated_at": self._now(),
        }
        if status == CHECKLIST_PENDING:
            payload["matched_document_queue_id"] = None
            payload["received_at"] = None
            payload["uploaded_by"] = None
        if status == CHECKLIST_DISPENSED:
            payload["received_at"] = None
        return self.update_status(status_id, payload)

    def get_status(
        self,
        checklist_id: str | None,
        client_code: str,
        competence: str,
    ) -> DocumentChecklistStatus | None:
        if not checklist_id:
            return None
        response = (
            self.client.table("document_checklist_status")
            .select("*")
            .eq("checklist_id", checklist_id)
            .eq("client_code", client_code)
            .eq("competence", competence)
            .limit(1)
            .execute()
        )
        rows: list[dict[str, Any]] = response.data or []
        return DocumentChecklistStatus.model_validate(rows[0]) if rows else None

    def create_status(
        self,
        checklist_item: ClientDocumentChecklist,
        competence: str,
        status: str = CHECKLIST_PENDING,
        auto_matched: bool = False,
    ) -> DocumentChecklistStatus:
        payload = {
            "checklist_id": checklist_item.id,
            "client_code": checklist_item.client_code,
            "competence": competence,
            "document_type": checklist_item.document_type,
            "file_extension": checklist_item.file_extension,
            "institution": checklist_item.institution,
            "status": status,
            "auto_matched": auto_matched,
            "updated_at": self._now(),
        }
        return self.create_status_from_payload(payload)

    def create_status_from_payload(self, payload: dict[str, Any]) -> DocumentChecklistStatus:
        response = self.client.table("document_checklist_status").insert(payload).execute()
        return DocumentChecklistStatus.model_validate((response.data or [payload])[0])

    def update_status(self, status_id: str, payload: dict[str, Any]) -> DocumentChecklistStatus:
        response = self.client.table("document_checklist_status").update(payload).eq("id", status_id).execute()
        rows: list[dict[str, Any]] = response.data or []
        if rows:
            return DocumentChecklistStatus.model_validate(rows[0])
        refreshed = self.client.table("document_checklist_status").select("*").eq("id", status_id).limit(1).execute()
        refreshed_rows: list[dict[str, Any]] = refreshed.data or []
        if not refreshed_rows:
            raise RuntimeError(f"Status do checklist nao encontrado apos update: {status_id}")
        return DocumentChecklistStatus.model_validate(refreshed_rows[0])

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalized_key(self, value: str | None) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _normalized_extension(self, value: str | None) -> str:
        return str(value or "").strip().lower().lstrip(".")
