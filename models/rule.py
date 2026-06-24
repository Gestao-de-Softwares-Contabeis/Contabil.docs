from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleType(str, Enum):
    MANUAL_OVERRIDE = "manual_override"
    OFX = "ofx"
    PDF = "pdf"
    SPREADSHEET = "spreadsheet"
    TEXT = "text"
    BANK_ACCOUNT = "bank_account"
    PARTNER_NAME = "partner_name"
    TEXT_TERM = "text_term"
    SPREADSHEET_TERM = "spreadsheet_term"
    CNPJ = "cnpj"
    FILENAME_TERM = "filename_term"


class DocumentRule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    client_id: str | None = None
    client_code: str | None = None
    client_name: str | None = None
    file_extension: str | None = None
    rule_type: str
    document_type: str | None = None
    institution: str | None = None
    rule_name: str | None = None
    rule_value: str | None = None
    bank_name: str | None = None
    agency: str | None = None
    account_number: str | None = None
    sheet_name: str | None = None
    column_name: str | None = None
    row_number: int | None = None
    match_mode: str = "contains"
    pattern: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    is_active: bool = True
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None
    hits_count: int = 0
    hit_count: int = 0
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_rule_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        data["active"] = data.get("active", data.get("is_active", True))
        data["is_active"] = data.get("is_active", data.get("active", True))
        data["hits_count"] = data.get("hits_count", data.get("hit_count", 0))
        data["hit_count"] = data.get("hit_count", data.get("hits_count", 0))
        data["document_type"] = data.get("document_type") or "documento_diverso"

        pattern = dict(data.get("pattern") or {})
        field_map = {
            "rule_value": data.get("rule_value"),
            "bank_name": data.get("bank_name"),
            "agency": data.get("agency"),
            "account_number": data.get("account_number"),
            "sheet_name": data.get("sheet_name"),
            "column_name": data.get("column_name"),
            "row_number": data.get("row_number"),
        }
        for key, raw in field_map.items():
            if raw not in (None, ""):
                pattern[key] = raw
        data["pattern"] = pattern
        return data
