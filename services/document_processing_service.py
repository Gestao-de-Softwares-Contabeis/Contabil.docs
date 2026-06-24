from __future__ import annotations

from models.document import (
    DocumentLogEntry,
    DocumentType,
    IdentificationResult,
    ProcessedDocument,
    ProcessingStatus,
    UploadedDocument,
)
from parsers.document_parsers import DocumentParserService
from repositories.log_repository import ProcessingLogRepository
from services.identification_service import IdentificationService
from utils.normalization import get_extension, sha256_bytes
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class DocumentProcessingService:
    def __init__(
        self,
        parser_service: DocumentParserService | None = None,
        identification_service: IdentificationService | None = None,
        log_repository: ProcessingLogRepository | None = None,
    ) -> None:
        self.parser_service = parser_service or DocumentParserService()
        self.identification_service = identification_service or IdentificationService()
        self.log_repository = log_repository or ProcessingLogRepository()

    def process_file(
        self,
        filename: str,
        content: bytes,
        sender_name: str,
        sender_department: str | None,
        origin_channel: str,
        upload_group: str | None = None,
    ) -> ProcessedDocument:
        file_hash = sha256_bytes(content)
        extension = get_extension(filename)
        self._write_log(
            action="DOCUMENTO_RECEBIDO",
            status=ProcessingStatus.RECEIVED,
            user_name=sender_name,
            user_department=sender_department,
            sender_name=sender_name,
            sender_department=sender_department,
            origin_channel=origin_channel,
            filename=filename,
            extension=extension,
            size_bytes=len(content),
            file_hash=file_hash,
            observation="Arquivo recebido.",
            metadata={"upload_group": upload_group} if upload_group else None,
        )
        self._write_log(
            action="DOCUMENTO_PROCESSANDO",
            status=ProcessingStatus.PROCESSING,
            user_name=sender_name,
            user_department=sender_department,
            sender_name=sender_name,
            sender_department=sender_department,
            origin_channel=origin_channel,
            filename=filename,
            extension=extension,
            size_bytes=len(content),
            file_hash=file_hash,
            observation="Processamento iniciado.",
            metadata={"upload_group": upload_group} if upload_group else None,
        )

        try:
            uploaded = self.parser_service.parse(filename, content)
            identification = self.identification_service.identify(uploaded)
            final_log = self._write_identification_log(
                uploaded,
                identification,
                sender_name,
                sender_department,
                origin_channel,
                upload_group,
            )
            logger.info(
                "Documento processado",
                extra={
                    "ctx_file_hash": uploaded.file_hash,
                    "ctx_status": identification.status.value,
                    "ctx_score": identification.score,
                },
            )
            return ProcessedDocument(uploaded=uploaded, identification=identification, log_id=final_log.id)
        except Exception as exc:
            logger.exception("Erro ao processar documento", extra={"ctx_filename": filename})
            uploaded = UploadedDocument(
                original_filename=filename,
                extension=extension,
                size_bytes=len(content),
                content=content,
                extracted_text="",
                file_hash=file_hash,
            )
            identification = IdentificationResult(
                document_type=DocumentType.OTHER,
                status=ProcessingStatus.IDENTIFICATION_ERROR,
                score=0,
                observation=f"Erro no processamento: {exc}",
            )
            final_log = self._write_identification_log(
                uploaded,
                identification,
                sender_name,
                sender_department,
                origin_channel,
                upload_group,
            )
            return ProcessedDocument(uploaded=uploaded, identification=identification, log_id=final_log.id)

    def confirm_dispatch(
        self,
        file_hash: str,
        user_name: str,
        user_department: str | None = None,
    ) -> DocumentLogEntry:
        current = self._find_current_document(file_hash)
        if not current:
            raise ValueError("Documento nao encontrado no historico.")

        blocked_reasons = []
        if current.status != ProcessingStatus.READY_TO_SEND.value:
            blocked_reasons.append("status diferente de PRONTO_ENVIO")
        if not current.client_id:
            blocked_reasons.append("cliente vazio")
        if not current.competence:
            blocked_reasons.append("competencia vazia")
        if not current.destination_folder:
            blocked_reasons.append("pasta destino vazia")

        if blocked_reasons:
            blocked = DocumentLogEntry(
                user_name=user_name,
                user_department=user_department,
                action="ENVIO_BLOQUEADO",
                client_id=current.client_id,
                client_name=current.client_name,
                original_filename=current.original_filename,
                file_extension=current.file_extension,
                file_size_bytes=current.file_size_bytes,
                file_hash=current.file_hash,
                competence=current.competence,
                document_type=current.document_type,
                institution=current.institution,
                score=current.score,
                score_band=current.score_band,
                matched_by=current.matched_by,
                ai_used=current.ai_used,
                sender_name=current.sender_name,
                sender_department=current.sender_department,
                origin_channel=current.origin_channel,
                status=ProcessingStatus.IDENTIFICATION_ERROR.value,
                destination_folder=current.destination_folder,
                extracted_text=current.extracted_text,
                observation="Envio bloqueado: " + ", ".join(blocked_reasons),
                metadata=current.metadata,
            )
            self.log_repository.insert(blocked)
            raise ValueError(blocked.observation or "Envio bloqueado.")

        entry = DocumentLogEntry(
            user_name=user_name,
            user_department=user_department,
            action="ENVIO_CONFIRMADO",
            client_id=current.client_id,
            client_name=current.client_name,
            original_filename=current.original_filename,
            file_extension=current.file_extension,
            file_size_bytes=current.file_size_bytes,
            file_hash=current.file_hash,
            competence=current.competence,
            document_type=current.document_type,
            institution=current.institution,
            score=current.score,
            score_band=current.score_band,
            matched_by=current.matched_by,
            ai_used=current.ai_used,
            sender_name=current.sender_name,
            sender_department=current.sender_department,
            origin_channel=current.origin_channel,
            status=ProcessingStatus.SENT.value,
            destination_folder=current.destination_folder,
            extracted_text=current.extracted_text,
            observation="Envio confirmado no MVP local; integracao n8n sera conectada depois.",
            metadata=current.metadata,
        )
        return self.log_repository.insert(entry)

    def request_parametrization(
        self,
        file_hash: str,
        user_name: str,
        user_department: str | None = None,
    ) -> DocumentLogEntry:
        current = self._find_current_document(file_hash)
        if not current:
            raise ValueError("Documento nao encontrado no historico.")

        if current.status != ProcessingStatus.IDENTIFICATION_ERROR.value:
            blocked = DocumentLogEntry(
                user_name=user_name,
                user_department=user_department,
                action="PARAMETRIZACAO_BLOQUEADA",
                client_id=current.client_id,
                client_name=current.client_name,
                original_filename=current.original_filename,
                file_extension=current.file_extension,
                file_size_bytes=current.file_size_bytes,
                file_hash=current.file_hash,
                competence=current.competence,
                document_type=current.document_type,
                institution=current.institution,
                score=current.score,
                score_band=current.score_band,
                matched_by=current.matched_by,
                ai_used=current.ai_used,
                sender_name=current.sender_name,
                sender_department=current.sender_department,
                origin_channel=current.origin_channel,
                status=current.status,
                destination_folder=current.destination_folder,
                extracted_text=current.extracted_text,
                observation="Parametrizacao bloqueada: identificacao automatica nao falhou.",
                metadata=current.metadata,
            )
            self.log_repository.insert(blocked)
            raise ValueError(blocked.observation or "Parametrizacao bloqueada.")

        entry = DocumentLogEntry(
            user_name=user_name,
            user_department=user_department,
            action="PARAMETRIZACAO_SOLICITADA",
            client_id=current.client_id,
            client_name=current.client_name,
            original_filename=current.original_filename,
            file_extension=current.file_extension,
            file_size_bytes=current.file_size_bytes,
            file_hash=current.file_hash,
            competence=current.competence,
            document_type=current.document_type,
            institution=current.institution,
            score=current.score,
            score_band=current.score_band,
            matched_by=current.matched_by,
            ai_used=current.ai_used,
            sender_name=current.sender_name,
            sender_department=current.sender_department,
            origin_channel=current.origin_channel,
            status=ProcessingStatus.WAITING_RULES.value,
            destination_folder=current.destination_folder,
            extracted_text=current.extracted_text,
            observation="Documento marcado para parametrizacao manual.",
            metadata=current.metadata,
        )
        return self.log_repository.insert(entry)

    def _find_current_document(self, file_hash: str) -> DocumentLogEntry | None:
        for document in self.log_repository.list_current_documents(limit=2000):
            if document.file_hash == file_hash:
                return document
        return None

    def _write_identification_log(
        self,
        uploaded: UploadedDocument,
        identification: IdentificationResult,
        sender_name: str,
        sender_department: str | None,
        origin_channel: str,
        upload_group: str | None = None,
    ) -> DocumentLogEntry:
        return self._write_log(
            action="DOCUMENTO_PROCESSADO",
            status=identification.status,
            user_name=sender_name,
            user_department=sender_department,
            sender_name=sender_name,
            sender_department=sender_department,
            origin_channel=origin_channel,
            filename=uploaded.original_filename,
            extension=uploaded.extension,
            size_bytes=uploaded.size_bytes,
            file_hash=uploaded.file_hash,
            client_id=identification.client_id,
            client_name=identification.client_name,
            competence=identification.competence,
            document_type=identification.document_type.value,
            institution=identification.institution,
            score=identification.score,
            score_band=identification.score_band.value,
            matched_by=identification.matched_by,
            ai_used=identification.ai_used,
            destination_folder=identification.destination_folder,
            extracted_text=uploaded.extracted_text,
            observation=identification.observation,
            metadata={
                "extracted_text_length": len(uploaded.extracted_text),
                "upload_group": upload_group,
                "parametrization_allowed": (
                    identification.status == ProcessingStatus.IDENTIFICATION_ERROR
                ),
            },
        )

    def _write_log(
        self,
        action: str,
        status: ProcessingStatus,
        user_name: str,
        user_department: str | None,
        sender_name: str,
        sender_department: str | None,
        origin_channel: str,
        filename: str,
        extension: str,
        size_bytes: int,
        file_hash: str,
        client_id: str | None = None,
        client_name: str | None = None,
        competence: str | None = None,
        document_type: str | None = None,
        institution: str | None = None,
        score: int | None = None,
        score_band: str | None = None,
        matched_by: str | None = None,
        ai_used: bool | None = None,
        destination_folder: str | None = None,
        extracted_text: str | None = None,
        observation: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> DocumentLogEntry:
        entry = DocumentLogEntry(
            user_name=user_name,
            user_department=user_department,
            action=action,
            client_id=client_id,
            client_name=client_name,
            original_filename=filename,
            file_extension=extension,
            file_size_bytes=size_bytes,
            file_hash=file_hash,
            competence=competence,
            document_type=document_type,
            institution=institution,
            score=score,
            score_band=score_band,
            matched_by=matched_by,
            ai_used=ai_used,
            sender_name=sender_name,
            sender_department=sender_department,
            origin_channel=origin_channel,
            status=status.value,
            destination_folder=destination_folder,
            extracted_text=extracted_text,
            observation=observation,
            metadata=metadata or {},
        )
        return self.log_repository.insert(entry)
