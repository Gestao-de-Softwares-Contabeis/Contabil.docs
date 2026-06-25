from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models.client import StorageRoute
from models.document import (
    CoreDocumentResult,
    CoreProcessingStatus,
    DocumentLogEntry,
    IdentificationResult,
    ProcessingStatus,
    UploadedDocument,
)
from models.integration import N8NDispatchResult, StorageUploadResult
from parsers.document_parsers import DocumentParserService
from repositories.log_repository import ProcessingLogRepository
from services.filename_builder import FilenameBuilder
from services.identification_service import IdentificationService
from services.n8n_dispatch_service import N8NDispatchService
from services.routing_service import RoutingService
from services.storage_service import SupabaseStorageService
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class AnalyzedDocumentDispatcher(Protocol):
    def dispatch_analyzed(self, result: CoreDocumentResult, storage: StorageUploadResult | None = None) -> N8NDispatchResult:
        pass


class StorageUploader(Protocol):
    def upload_and_sign(self, document: UploadedDocument, storage_path: str | None = None) -> StorageUploadResult:
        pass


class CoreProcessor:
    def __init__(
        self,
        parser_service: DocumentParserService | None = None,
        identification_service: IdentificationService | None = None,
        routing_service: RoutingService | None = None,
        filename_builder: FilenameBuilder | None = None,
        storage_service: StorageUploader | None = None,
        n8n_dispatch_service: AnalyzedDocumentDispatcher | None = None,
        log_repository: ProcessingLogRepository | None = None,
    ) -> None:
        self.parser_service = parser_service or DocumentParserService()
        self.identification_service = identification_service or IdentificationService()
        self.routing_service = routing_service or RoutingService()
        self.filename_builder = filename_builder or FilenameBuilder()
        self.storage_service = storage_service
        self.n8n_dispatch_service = n8n_dispatch_service or N8NDispatchService()
        self.log_repository = log_repository

    def process_paths(
        self,
        file_paths: list[str | Path],
        department: str,
    ) -> list[CoreDocumentResult]:
        return [self.analyze_path(file_path, department=department) for file_path in file_paths]

    def process_path(
        self,
        file_path: str | Path,
        department: str,
    ) -> CoreDocumentResult:
        return self.analyze_path(file_path, department=department)

    def analyze_path(
        self,
        file_path: str | Path,
        department: str,
        upload_to_storage: bool = True,
    ) -> CoreDocumentResult:
        uploaded = self.parser_service.parse_path(file_path)
        return self.analyze_document(uploaded, department=department, upload_to_storage=upload_to_storage)

    def process_file(
        self,
        filename: str,
        content: bytes,
        department: str,
    ) -> CoreDocumentResult:
        return self.analyze_file(filename, content, department=department)

    def analyze_file(
        self,
        filename: str,
        content: bytes,
        department: str,
        upload_to_storage: bool = True,
    ) -> CoreDocumentResult:
        uploaded = self.parser_service.parse(filename, content)
        return self.analyze_document(uploaded, department=department, upload_to_storage=upload_to_storage)

    def process_document(
        self,
        uploaded: UploadedDocument,
        department: str,
    ) -> CoreDocumentResult:
        return self.analyze_document(uploaded, department=department)

    def analyze_document(
        self,
        uploaded: UploadedDocument,
        department: str,
        upload_to_storage: bool = True,
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
        if upload_to_storage:
            self._upload_storage_if_ready(uploaded, result)
        return result

    def confirm_and_send(
        self,
        result: CoreDocumentResult,
        user_name: str = "sistema",
        user_department: str | None = None,
        source_channel: str | None = None,
    ) -> CoreDocumentResult:
        if result.status != CoreProcessingStatus.READY_TO_SEND:
            raise ValueError("Somente documentos PRONTO_ENVIO podem ser enviados ao n8n.")
        if not result.storage_upload:
            raise ValueError("Resultado analisado sem upload no Supabase Storage.")

        dispatch_result = self.n8n_dispatch_service.dispatch_analyzed(result)
        result.n8n_dispatch = dispatch_result.model_dump(mode="json", exclude_none=True)
        result.extracted_summary["n8n_dispatch"] = result.n8n_dispatch
        self._write_confirm_log(
            result=result,
            dispatch_result=dispatch_result,
            user_name=user_name,
            user_department=user_department,
            source_channel=source_channel,
        )
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

    def _upload_storage_if_ready(self, uploaded: UploadedDocument, result: CoreDocumentResult) -> None:
        if result.status != CoreProcessingStatus.READY_TO_SEND:
            return
        try:
            storage_service = self.storage_service or SupabaseStorageService()
            storage_result = storage_service.upload_and_sign(uploaded)
            result.storage_upload = storage_result.model_dump(mode="json", exclude_none=True)
            result.extracted_summary["storage_upload"] = result.storage_upload
        except Exception as exc:
            logger.exception(
                "Erro inesperado ao subir arquivo no Storage durante analise",
                extra={"ctx_file": uploaded.original_filename, "ctx_file_hash": uploaded.file_hash},
            )
            result.storage_upload = {"upload_ok": False, "error": str(exc)}
            result.extracted_summary["storage_upload"] = result.storage_upload

    def _write_confirm_log(
        self,
        result: CoreDocumentResult,
        dispatch_result: N8NDispatchResult,
        user_name: str,
        user_department: str | None,
        source_channel: str | None,
    ) -> None:
        repository = self.log_repository or ProcessingLogRepository()
        status = ProcessingStatus.SENT.value if dispatch_result.send_ok else ProcessingStatus.READY_TO_SEND.value
        action = "N8N_ENVIO_CONFIRMADO" if dispatch_result.send_ok else "N8N_ENVIO_FALHOU"
        observation = (
            "Documento enviado ao webhook n8n."
            if dispatch_result.send_ok
            else f"Falha ao enviar ao webhook n8n: {dispatch_result.error or dispatch_result.n8n_response_body or 'sem detalhe'}"
        )
        repository.insert(
            DocumentLogEntry(
                user_name=user_name,
                user_department=user_department,
                action=action,
                client_id=result.detected_client_code,
                client_name=result.detected_client_name,
                original_filename=result.original_file_name,
                file_extension=result.extension,
                competence=result.competence,
                document_type=result.document_type,
                institution=result.institution,
                score=int(result.confidence * 100),
                matched_by=str(result.extracted_summary.get("matched_by") or ""),
                ai_used=bool(result.extracted_summary.get("ai_used") or False),
                origin_channel=source_channel,
                status=status,
                destination_folder=result.destination_folder_id,
                observation=observation,
                metadata={
                    "client_code": result.detected_client_code,
                    "client_cnpj": result.detected_client_cnpj,
                    "new_file_name": result.new_file_name,
                    "destination_folder_id": result.destination_folder_id,
                    "destination_path_readable": result.destination_path_readable,
                    "storage_upload": result.storage_upload,
                    "n8n_dispatch": result.n8n_dispatch,
                },
            )
        )

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
