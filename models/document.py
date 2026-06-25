from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    BANK_STATEMENT = "extrato_bancario"
    FINANCIAL_REPORT = "relatorio_financeiro"
    FINANCIAL_REPORT_PAID = "relatorio_financeiro_contas_pagas"
    FINANCIAL_REPORT_RECEIVED = "relatorio_financeiro_contas_recebidas"
    CREDIT_CARD_INVOICE = "fatura_cartao_credito"
    CARD_REPORT = "relatorio_cartao"
    INVESTMENT_POSITION = "posicao_investimentos"
    INVESTMENT_INCOME = "rendimentos_investimentos"
    OFX = "ofx"
    RECEIPT = "comprovante"
    OTHER = "documento_diverso"


class ProcessingStatus(str, Enum):
    RECEIVED = "RECEBIDO"
    PROCESSING = "PROCESSANDO"
    READY_TO_SEND = "PRONTO_ENVIO"
    IDENTIFICATION_ERROR = "ERRO_IDENTIFICACAO"
    WAITING_RULES = "AGUARDANDO_PARAMETRIZACAO"
    SENT = "ENVIADO"


class ScoreBand(str, Enum):
    READY_TO_SEND = "PRONTO_ENVIO"
    REVIEW = "REVISAR"
    PARAMETERIZE = "PARAMETRIZAR"


class CoreProcessingStatus(str, Enum):
    READY_TO_SEND = "PRONTO_ENVIO"
    REVIEW = "REVISAR"
    IDENTIFICATION_ERROR = "ERRO_IDENTIFICACAO"


class UploadedDocument(BaseModel):
    original_filename: str
    extension: str
    size_bytes: int
    content: bytes = Field(repr=False)
    extracted_text: str = ""
    file_hash: str


class IdentificationResult(BaseModel):
    client_id: str | None = None
    client_code: str | None = None
    client_name: str | None = None
    client_cnpj: str | None = None
    competence: str | None = None
    document_type: DocumentType = DocumentType.OTHER
    institution: str | None = None
    score: int = 0
    score_band: ScoreBand = ScoreBand.PARAMETERIZE
    destination_folder: str | None = None
    status: ProcessingStatus = ProcessingStatus.IDENTIFICATION_ERROR
    matched_by: str = "manual_review"
    observation: str = ""
    ai_used: bool = False
    review_reason: str | None = None
    suggested_rule_type: str | None = None
    extracted_bank_name: str | None = None
    extracted_agency: str | None = None
    extracted_account_number: str | None = None
    extracted_partner_candidates: list[str] = Field(default_factory=list)
    extracted_terms_candidates: list[str] = Field(default_factory=list)
    identification_signals: dict[str, Any] = Field(
        default_factory=lambda: {
            "client_code": None,
            "manual_override": None,
            "cnpj": None,
            "company_name": None,
            "bank_account": None,
            "partner_name": None,
            "openai": None,
        }
    )


class DocumentLogEntry(BaseModel):
    id: str | None = None
    created_at: datetime | None = None
    user_name: str
    user_department: str | None = None
    action: str
    client_id: str | None = None
    client_name: str | None = None
    original_filename: str | None = None
    file_extension: str | None = None
    file_size_bytes: int | None = None
    file_hash: str | None = None
    competence: str | None = None
    document_type: str | None = None
    institution: str | None = None
    score: int | None = None
    score_band: str | None = None
    matched_by: str | None = None
    ai_used: bool | None = None
    sender_name: str | None = None
    sender_department: str | None = None
    origin_channel: str | None = None
    status: str
    destination_folder: str | None = None
    extracted_text: str | None = None
    observation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessedDocument(BaseModel):
    uploaded: UploadedDocument
    identification: IdentificationResult
    log_id: str | None = None


class CoreDocumentResult(BaseModel):
    original_file_name: str
    extension: str
    detected_client_code: str | None = None
    detected_client_name: str | None = None
    detected_client_cnpj: str | None = None
    competence: str | None = None
    document_type: str
    institution: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    status: CoreProcessingStatus
    destination_folder_id: str | None = None
    destination_path_readable: str | None = None
    new_file_name: str | None = None
    review_reason: str | None = None
    identification_signals: dict[str, Any] = Field(default_factory=dict)
    extracted_bank_name: str | None = None
    extracted_agency: str | None = None
    extracted_account_number: str | None = None
    extracted_partner_candidates: list[str] = Field(default_factory=list)
    extracted_terms_candidates: list[str] = Field(default_factory=list)
    suggested_rule_type: str | None = None
    storage_upload: dict[str, Any] = Field(default_factory=dict)
    n8n_dispatch: dict[str, Any] = Field(default_factory=dict)
    extracted_summary: dict[str, Any] = Field(default_factory=dict)
