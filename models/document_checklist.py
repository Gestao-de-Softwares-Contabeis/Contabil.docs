from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


CHECKLIST_PENDING = "PENDENTE"
CHECKLIST_RECEIVED = "RECEBIDO"
CHECKLIST_DISPENSED = "DISPENSADO"


class ClientDocumentChecklist(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    client_code: str
    document_type: str
    file_extension: str | None = None
    institution: str | None = None
    document_name_pattern: str | None = None
    description: str | None = None
    department: str = "contabil"
    is_required: bool = True
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentChecklistStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    checklist_id: str | None = None
    client_code: str
    competence: str
    document_type: str
    file_extension: str | None = None
    institution: str | None = None
    status: str = CHECKLIST_PENDING
    matched_document_queue_id: str | None = None
    uploaded_by: str | None = None
    auto_matched: bool = True
    received_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChecklistDashboardItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_code: str
    competence: str
    total: int = 0
    recebidos: int = 0
    pendentes: int = 0
    dispensados: int = 0
