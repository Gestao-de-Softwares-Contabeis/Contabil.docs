from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from models.document import CoreDocumentResult


class ConflictResolutionRequest(BaseModel):
    file_path: str | Path
    department: str
    selected_client_code: str
    created_by: str
    created_by_department: str | None = None
    correction_value: str | None = None
    rule_ids_to_deactivate: list[str] = Field(default_factory=list)
    notes: str | None = None


class ConflictResolutionResult(BaseModel):
    created_rule_id: str | None
    deactivated_rule_ids: list[str] = Field(default_factory=list)
    initial_result: CoreDocumentResult
    reprocessed_result: CoreDocumentResult
    validation_passed: bool
