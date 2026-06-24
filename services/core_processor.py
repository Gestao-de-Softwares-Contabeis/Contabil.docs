from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models.client import StorageRoute
from models.document import CoreDocumentResult, CoreProcessingStatus, IdentificationResult, UploadedDocument
from models.integration import N8NDispatchResult
from parsers.document_parsers import DocumentParserService
from services.filename_builder import FilenameBuilder
from services.identification_service import IdentificationService
from services.n8n_dispatch_service import N8NDispatchService
from services.routing_service import RoutingService
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class ReadyDocumentDispatcher(Protocol):
    def dispatch(self, document: UploadedDocument, result: CoreDocumentResult) -> N8NDispatchResult:
        pass


class CoreProcessor:
    def __init__(
        self,
        parser_service: DocumentParserService | None = None,
        identification_service: IdentificationService | None = None,
        routing_service: RoutingService | None = None,
        filename_builder: FilenameBuilder | None = None,
        n8n_dispatch_service: ReadyDocumentDispatcher | None = None,
    ) -> None:
        self.parser_service = parser_service or DocumentParserService()
        self.identification_service = identification_service or IdentificationService()
        self.routing_service = routing_service or RoutingService()
        self.filename_builder = filename_builder or FilenameBuilder()
        self.n8n_dispatch_service = n8n_dispatch_service or N8NDispatchService()

    def process_paths(
        self,
        file_paths: list[str | Path],
        department: str,
    ) -> list[CoreDocumentResult]:
        return [self.process_path(file_path, department=department) for file_path in file_paths]

    def process_path(
        self,
        file_path: str | Path,
        department: str,
    ) -> CoreDocumentResult:
        uploaded = self.parser_service.parse_path(file_path)
        return self.process_document(uploaded, department=department)

    def process_file(
        self,
        filename: str,
        content: bytes,
        department: str,
    ) -> CoreDocumentResult:
        uploaded = self.parser_service.parse(filename, content)
        return self.process_document(uploaded, department=department)

    def process_document(
        self,
        uploaded: UploadedDocument,
        department: str,
    ) -> CoreDocumentResult:
        identification = self.identification_service.identify(uploaded, require_destination=False)
        route = self.routing_service.resolve_route(
            client_code=identification.client_code,
            department=department,
            competence=identification.competence,
        )
        new_file_name = self.filename_builder.build(
            client_name=identification.client_name,
            institution=identification.institution,
            competence=identification.competence,
            document_type=identification.document_type.value,
            extension=uploaded.extension,
            client_code=identification.client_code,
        )
        missing_fields = self._missing_required_fields(identification, route)
        confidence = round(identification.score / 100, 2)
        status = self._status_for(confidence, missing_fields, identification.review_reason)
        review_reason = self._review_reason(confidence, missing_fields, identification)
        summary = self._summary(uploaded, identification, route, department, missing_fields)

        result = CoreDocumentResult(
            original_file_name=uploaded.original_filename,
            extension=uploaded.extension,
            detected_client_code=identification.client_code,
            detected_client_name=identification.client_name,
            detected_client_cnpj=identification.client_cnpj,
            competence=identification.competence,
            document_type=identification.document_type.value,
            institution=identification.institution,
            confidence=confidence,
            status=status,
            destination_folder_id=route.destination_folder_id if route else None,
            destination_path_readable=route.destination_path_readable if route else None,
            new_file_name=new_file_name if status != CoreProcessingStatus.IDENTIFICATION_ERROR else None,
            review_reason=review_reason,
            identification_signals=identification.identification_signals,
            extracted_bank_name=identification.extracted_bank_name,
            extracted_agency=identification.extracted_agency,
            extracted_account_number=identification.extracted_account_number,
            extracted_partner_candidates=identification.extracted_partner_candidates,
            extracted_terms_candidates=identification.extracted_terms_candidates,
            suggested_rule_type=identification.suggested_rule_type,
            extracted_summary=summary,
        )
        self._dispatch_if_ready(uploaded, result)
        return result

    def _missing_required_fields(
        self,
        identification: IdentificationResult,
        route: StorageRoute | None,
    ) -> list[str]:
        missing_fields: list[str] = []
        if not identification.client_code:
            missing_fields.append("cliente")
        if not identification.competence:
            missing_fields.append("competencia")
        if not route or not route.destination_folder_id:
            missing_fields.append("pasta_destino")
        return missing_fields

    def _status_for(
        self,
        confidence: float,
        missing_fields: list[str],
        review_reason: str | None,
    ) -> CoreProcessingStatus:
        if review_reason:
            return CoreProcessingStatus.REVIEW
        if missing_fields:
            return CoreProcessingStatus.IDENTIFICATION_ERROR
        if confidence >= 0.90:
            return CoreProcessingStatus.READY_TO_SEND
        if confidence >= 0.70:
            return CoreProcessingStatus.REVIEW
        return CoreProcessingStatus.IDENTIFICATION_ERROR

    def _review_reason(
        self,
        confidence: float,
        missing_fields: list[str],
        identification: IdentificationResult,
    ) -> str | None:
        if identification.review_reason:
            return identification.review_reason

        if not missing_fields and confidence >= 0.90:
            return None

        reasons: list[str] = []
        if missing_fields:
            reasons.append("Campos obrigatorios ausentes: " + ", ".join(missing_fields))
        if not missing_fields and 0.70 <= confidence < 0.90:
            reasons.append("Confianca entre 0.70 e 0.89; revisar antes do envio.")
        if not missing_fields and confidence < 0.70:
            reasons.append("Confianca abaixo de 0.70.")
        if identification.observation:
            reasons.append(identification.observation)
        return " ".join(reasons) or None

    def _dispatch_if_ready(self, uploaded: UploadedDocument, result: CoreDocumentResult) -> None:
        if result.status != CoreProcessingStatus.READY_TO_SEND:
            return
        try:
            dispatch_result = self.n8n_dispatch_service.dispatch(uploaded, result)
            result.n8n_dispatch = dispatch_result.model_dump(mode="json", exclude_none=True)
            result.extracted_summary["n8n_dispatch"] = result.n8n_dispatch
        except Exception as exc:
            logger.exception(
                "Erro inesperado ao acionar envio n8n",
                extra={"ctx_file": uploaded.original_filename, "ctx_file_hash": uploaded.file_hash},
            )
            result.n8n_dispatch = {"send_ok": False, "error": str(exc)}
            result.extracted_summary["n8n_dispatch"] = result.n8n_dispatch

    def _summary(
        self,
        uploaded: UploadedDocument,
        identification: IdentificationResult,
        route: StorageRoute | None,
        department: str,
        missing_fields: list[str],
    ) -> dict[str, object]:
        summary = self.parser_service.build_summary(uploaded)
        summary.update(
            {
                "matched_by": identification.matched_by,
                "ai_used": identification.ai_used,
                "score": identification.score,
                "observation": identification.observation,
                "department": department,
                "route_found": route is not None,
                "missing_fields": missing_fields,
                "suggested_rule_type": identification.suggested_rule_type,
                "extracted_bank_name": identification.extracted_bank_name,
                "extracted_agency": identification.extracted_agency,
                "extracted_account_number": identification.extracted_account_number,
                "extracted_partner_candidates": identification.extracted_partner_candidates,
                "extracted_terms_candidates": identification.extracted_terms_candidates,
            }
        )
        return summary
