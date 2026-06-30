from __future__ import annotations

from models.document_checklist import CHECKLIST_RECEIVED, ClientDocumentChecklist, DocumentChecklistStatus
from models.document_queue import DocumentQueueItem
from repositories.document_checklist_repository import DocumentChecklistRepository
from utils.normalization import normalize_text
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class ChecklistService:
    def __init__(self, repository: DocumentChecklistRepository | None = None) -> None:
        self.repository = repository or DocumentChecklistRepository()

    def mark_received_after_send(self, queue_item: DocumentQueueItem) -> DocumentChecklistStatus | None:
        if not queue_item.client_code or not queue_item.competence or not queue_item.document_type or not queue_item.extension:
            logger.warning("Nenhum checklist correspondente encontrado", extra=self.match_context(queue_item))
            return None

        checklist_item = self.match_checklist_item(queue_item)
        if not checklist_item:
            logger.warning("Nenhum checklist correspondente encontrado", extra=self.match_context(queue_item))
            return None

        logger.info(
            "Checklist match encontrado",
            extra={**self.match_context(queue_item), "ctx_checklist_id": checklist_item.id},
        )
        status = self.repository.mark_received(checklist_item, queue_item)
        logger.info(
            "Checklist status atualizado para RECEBIDO",
            extra={**self.match_context(queue_item), "ctx_checklist_id": checklist_item.id},
        )
        return status

    def mark_document_received(self, queue_item: DocumentQueueItem) -> list[DocumentChecklistStatus]:
        status = self.mark_received_after_send(queue_item)
        return [status] if status else []

    def match_context(self, queue_item: DocumentQueueItem) -> dict[str, str | None]:
        return {
            "ctx_client_code": queue_item.client_code,
            "ctx_competence": queue_item.competence,
            "ctx_document_type": queue_item.document_type,
            "ctx_institution": queue_item.institution,
            "ctx_extension": queue_item.extension,
        }

    def ensure_monthly_statuses(
        self,
        client_code: str,
        competence: str,
    ) -> list[DocumentChecklistStatus]:
        return self.repository.ensure_monthly_statuses(client_code, competence)

    def matches(
        self,
        checklist_item: ClientDocumentChecklist,
        queue_item: DocumentQueueItem,
    ) -> bool:
        return self._required_match(checklist_item, queue_item)

    def match_checklist_item(
        self,
        queue_item: DocumentQueueItem,
        checklist_items: list[ClientDocumentChecklist] | None = None,
        log_ambiguity: bool = True,
    ) -> ClientDocumentChecklist | None:
        if not queue_item.client_code or not queue_item.document_type or not queue_item.extension:
            return None

        items = checklist_items if checklist_items is not None else self.repository.list_checklist(client_code=queue_item.client_code)
        candidates = [
            checklist_item
            for checklist_item in items
            if self._required_match(checklist_item, queue_item)
        ]
        if not candidates:
            return None

        scored_candidates = [
            (self._optional_match_score(checklist_item, queue_item), index, checklist_item)
            for index, checklist_item in enumerate(candidates)
        ]
        best_score = max(score for score, _, _ in scored_candidates)
        best_candidates = [item for score, _, item in scored_candidates if score == best_score]
        if len(best_candidates) > 1 and log_ambiguity:
            logger.warning(
                "Checklist com match ambiguo; usando primeiro item fixo encontrado",
                extra={
                    **self.match_context(queue_item),
                    "ctx_candidates": ",".join(str(item.id) for item in best_candidates if item.id),
                },
            )
        return min(scored_candidates, key=lambda scored: (-scored[0], scored[1]))[2]

    def build_monthly_matrix(
        self,
        checklist_items: list[ClientDocumentChecklist],
        sent_documents: list[DocumentQueueItem],
        competences: list[str],
        received_statuses: list[DocumentChecklistStatus] | None = None,
    ) -> list[dict[str, object]]:
        statuses = received_statuses or []
        rows: list[dict[str, object]] = []
        for checklist_item in checklist_items:
            row: dict[str, object] = {
                "document_type": checklist_item.document_type,
                "institution": checklist_item.institution,
                "file_extension": checklist_item.file_extension or "qualquer",
                "description": checklist_item.description,
            }
            for competence in competences:
                row[competence] = (
                    "RECEBIDO"
                    if self._has_received_status(checklist_item, competence, statuses)
                    or self._has_sent_document(checklist_item, competence, sent_documents, checklist_items)
                    else "PENDENTE"
                )
            rows.append(row)
        return rows

    def build_monthly_summary(
        self,
        matrix_rows: list[dict[str, object]],
        competences: list[str],
        client_code: str,
    ) -> list[dict[str, object]]:
        summary: list[dict[str, object]] = []
        for competence in competences:
            statuses = [str(row.get(competence) or "PENDENTE") for row in matrix_rows]
            total = len(statuses)
            received = statuses.count("RECEBIDO")
            pending = total - received
            summary.append(
                {
                    "cliente": client_code,
                    "competencia": competence,
                    "total esperado": total,
                    "recebidos": received,
                    "pendentes": pending,
                    "percentual recebido": f"{((received / total) * 100):.0f}%" if total else "0%",
                }
            )
        return summary

    def _has_sent_document(
        self,
        checklist_item: ClientDocumentChecklist,
        competence: str,
        sent_documents: list[DocumentQueueItem],
        checklist_items: list[ClientDocumentChecklist],
    ) -> bool:
        for document in sent_documents:
            if document.competence != competence:
                continue
            matched_item = self.match_checklist_item(document, checklist_items, log_ambiguity=False)
            if matched_item and self._same_checklist_item(matched_item, checklist_item):
                return True
        return False

    def _has_received_status(
        self,
        checklist_item: ClientDocumentChecklist,
        competence: str,
        received_statuses: list[DocumentChecklistStatus],
    ) -> bool:
        for status in received_statuses:
            if status.status != CHECKLIST_RECEIVED or status.competence != competence:
                continue
            if checklist_item.id and status.checklist_id == checklist_item.id:
                return True
            if (
                normalize_text(status.client_code) == normalize_text(checklist_item.client_code)
                and normalize_text(status.document_type) == normalize_text(checklist_item.document_type)
                and self._normalize_extension(status.file_extension) == self._normalize_extension(checklist_item.file_extension)
            ):
                return True
        return False

    def _same_checklist_item(
        self,
        left: ClientDocumentChecklist,
        right: ClientDocumentChecklist,
    ) -> bool:
        if left.id and right.id:
            return left.id == right.id
        return (
            normalize_text(left.client_code) == normalize_text(right.client_code)
            and normalize_text(left.document_type) == normalize_text(right.document_type)
            and self._normalize_extension(left.file_extension) == self._normalize_extension(right.file_extension)
            and normalize_text(left.institution) == normalize_text(right.institution)
            and normalize_text(left.document_name_pattern) == normalize_text(right.document_name_pattern)
        )

    def _required_match(
        self,
        checklist_item: ClientDocumentChecklist,
        queue_item: DocumentQueueItem,
    ) -> bool:
        return (
            normalize_text(checklist_item.client_code) == normalize_text(queue_item.client_code)
            and normalize_text(checklist_item.document_type) == normalize_text(queue_item.document_type)
            and bool(checklist_item.file_extension)
            and bool(queue_item.extension)
            and self._normalize_extension(checklist_item.file_extension) == self._normalize_extension(queue_item.extension)
        )

    def _optional_match_score(
        self,
        checklist_item: ClientDocumentChecklist,
        queue_item: DocumentQueueItem,
    ) -> int:
        score = 0
        if checklist_item.institution and queue_item.institution:
            if normalize_text(checklist_item.institution) == normalize_text(queue_item.institution):
                score += 2
        if checklist_item.document_name_pattern:
            pattern = normalize_text(checklist_item.document_name_pattern)
            if pattern and pattern in self._document_match_source(queue_item):
                score += 3
        return score

    def _normalize_extension(self, value: str | None) -> str:
        return str(value or "").lower().lstrip(".").strip()

    def _document_match_source(self, queue_item: DocumentQueueItem) -> str:
        payload = queue_item.payload_json or {}
        summary = payload.get("extracted_summary") if isinstance(payload.get("extracted_summary"), dict) else {}
        core_result = payload.get("core_result") if isinstance(payload.get("core_result"), dict) else {}
        parts = [
            queue_item.original_file_name,
            queue_item.new_file_name,
            queue_item.document_type,
            queue_item.institution,
            queue_item.review_reason,
            summary.get("text_preview") if isinstance(summary, dict) else None,
            " ".join(summary.get("terms_candidates") or []) if isinstance(summary, dict) else None,
            core_result.get("original_file_name") if isinstance(core_result, dict) else None,
            core_result.get("new_file_name") if isinstance(core_result, dict) else None,
        ]
        return normalize_text(" ".join(str(part) for part in parts if part))
