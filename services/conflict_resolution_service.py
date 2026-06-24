from __future__ import annotations

import json
from pathlib import Path

from models.conflict_resolution import ConflictResolutionRequest, ConflictResolutionResult
from models.document import CoreDocumentResult, CoreProcessingStatus, DocumentLogEntry, ProcessingStatus
from models.rule import DocumentRule, RuleType
from repositories.client_repository import ClientRepository
from repositories.log_repository import ProcessingLogRepository
from repositories.rule_repository import RuleRepository
from services.core_processor import CoreProcessor


class ConflictResolutionService:
    def __init__(
        self,
        core_processor: CoreProcessor | None = None,
        client_repository: ClientRepository | None = None,
        rule_repository: RuleRepository | None = None,
        log_repository: ProcessingLogRepository | None = None,
    ) -> None:
        self.core_processor = core_processor or CoreProcessor()
        self.client_repository = client_repository or ClientRepository()
        self.rule_repository = rule_repository or RuleRepository()
        self.log_repository = log_repository or ProcessingLogRepository()

    def resolve_and_reprocess(self, request: ConflictResolutionRequest) -> ConflictResolutionResult:
        file_path = Path(request.file_path)
        initial_result = self.core_processor.process_path(file_path, department=request.department)
        self._validate_initial_conflict(initial_result)

        client = self.client_repository.get_by_client_code(request.selected_client_code)
        if not client or not client.client_code:
            raise ValueError(f"Cliente {request.selected_client_code} nao encontrado no Supabase.")

        deactivated_rule_ids = self._deactivate_wrong_rules(
            request.rule_ids_to_deactivate,
            request.created_by,
            request.created_by_department,
            file_path.name,
        )

        rule = DocumentRule(
            client_code=client.client_code,
            file_extension=initial_result.extension,
            document_type=initial_result.document_type,
            rule_type=RuleType.MANUAL_OVERRIDE.value,
            rule_name="Resolucao manual de conflito",
            rule_value=request.correction_value or initial_result.original_file_name,
            match_mode="contains",
            is_active=True,
            created_by=request.created_by,
            notes=self._build_notes(request, initial_result),
        )
        saved_rule = self.rule_repository.create(rule)
        self._write_resolution_log(
            action="REGRA_CORRETIVA_CRIADA",
            request=request,
            result=initial_result,
            created_rule_id=saved_rule.id,
            deactivated_rule_ids=deactivated_rule_ids,
        )

        reprocessed_result = self.core_processor.process_path(file_path, department=request.department)
        validation_passed = (
            reprocessed_result.status == CoreProcessingStatus.READY_TO_SEND
            and reprocessed_result.detected_client_code == client.client_code
        )
        self._write_resolution_log(
            action="DOCUMENTO_REPROCESSADO_APOS_REGRA_CORRETIVA",
            request=request,
            result=reprocessed_result,
            created_rule_id=saved_rule.id,
            deactivated_rule_ids=deactivated_rule_ids,
            validation_passed=validation_passed,
        )

        return ConflictResolutionResult(
            created_rule_id=saved_rule.id,
            deactivated_rule_ids=deactivated_rule_ids,
            initial_result=initial_result,
            reprocessed_result=reprocessed_result,
            validation_passed=validation_passed,
        )

    def _validate_initial_conflict(self, result: CoreDocumentResult) -> None:
        reason = result.review_reason or ""
        if result.status != CoreProcessingStatus.REVIEW or "Conflito entre sinais fortes" not in reason:
            raise ValueError("Resolucao manual permitida apenas para documentos em REVISAR por conflito de sinais.")

    def _deactivate_wrong_rules(
        self,
        rule_ids: list[str],
        user_name: str,
        user_department: str | None,
        original_file_name: str,
    ) -> list[str]:
        deactivated: list[str] = []
        for rule_id in rule_ids:
            if not rule_id:
                continue
            self.rule_repository.set_active(rule_id, False)
            deactivated.append(rule_id)
            self.log_repository.insert(
                DocumentLogEntry(
                    user_name=user_name,
                    user_department=user_department,
                    action="REGRA_INATIVADA_POR_CONFLITO",
                    original_filename=original_file_name,
                    status=ProcessingStatus.WAITING_RULES.value,
                    observation=f"Regra {rule_id} marcada como inativa durante resolucao manual de conflito.",
                    metadata={"rule_id": rule_id},
                )
            )
        return deactivated

    def _build_notes(self, request: ConflictResolutionRequest, result: CoreDocumentResult) -> str:
        payload = {
            "source": "manual_conflict_resolution",
            "original_file_name": result.original_file_name,
            "previous_status": result.status.value,
            "previous_review_reason": result.review_reason,
            "selected_client_code": request.selected_client_code,
            "user_notes": request.notes,
        }
        return json.dumps(payload, ensure_ascii=True)

    def _write_resolution_log(
        self,
        action: str,
        request: ConflictResolutionRequest,
        result: CoreDocumentResult,
        created_rule_id: str | None,
        deactivated_rule_ids: list[str],
        validation_passed: bool | None = None,
    ) -> None:
        summary = result.extracted_summary or {}
        self.log_repository.insert(
            DocumentLogEntry(
                user_name=request.created_by,
                user_department=request.created_by_department,
                action=action,
                client_id=result.detected_client_code or request.selected_client_code,
                client_name=result.detected_client_name,
                original_filename=result.original_file_name,
                file_extension=result.extension,
                competence=result.competence,
                document_type=result.document_type,
                institution=result.institution,
                score=int(result.confidence * 100),
                matched_by=summary.get("matched_by"),
                ai_used=summary.get("ai_used"),
                status=result.status.value,
                destination_folder=result.destination_folder_id,
                observation=result.review_reason or action,
                metadata={
                    "created_rule_id": created_rule_id,
                    "deactivated_rule_ids": deactivated_rule_ids,
                    "validation_passed": validation_passed,
                    "selected_client_code": request.selected_client_code,
                    "destination_path_readable": result.destination_path_readable,
                    "new_file_name": result.new_file_name,
                },
            )
        )
