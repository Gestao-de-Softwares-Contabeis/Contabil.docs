from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BankAccount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bank: str | None = None
    agency: str | None = None
    account: str


class Client(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    client_code: str | None = None
    name: str = ""
    client_name: str | None = None
    normalized_name: str | None = None
    cnpj: str | None = None
    client_cnpj: str | None = None
    status: str | None = None
    aliases: list[str] = Field(default_factory=list)
    bank_accounts: list[BankAccount] = Field(default_factory=list)
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_supabase_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        data["name"] = data.get("name") or data.get("client_name") or data.get("razao_social") or ""
        data["client_name"] = data.get("client_name") or data.get("name")
        data["cnpj"] = data.get("cnpj") or data.get("client_cnpj")
        data["client_cnpj"] = data.get("client_cnpj") or data.get("cnpj")
        data["client_code"] = data.get("client_code") or data.get("codigo") or data.get("code")
        if "active" not in data:
            status = data.get("status")
            data["active"] = True if status is None else str(status).lower() in {"active", "activate"}
        return data

    @field_validator("bank_accounts", mode="before")
    @classmethod
    def parse_bank_accounts(cls, value: Any) -> list[BankAccount] | Any:
        if value in (None, ""):
            return []
        return value

    @field_validator("aliases", mode="before")
    @classmethod
    def parse_aliases(cls, value: Any) -> list[str] | Any:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


class StorageRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    client_id: str | None = None
    client_code: str | None = None
    client_name: str | None = None
    client_cnpj: str | None = None
    department: str | None = None
    competence: str | None = None
    document_type: str | None = None
    destination_folder: str | None = None
    destination_folder_id: str | None = None
    destination_path_readable: str | None = None
    onedrive_competence_folder_id: str | None = None
    client_folder_name: str | None = None
    department_folder_name: str | None = None
    competence_folder_name: str | None = None
    status: str | None = None
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_route_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        folder_id = (
            data.get("destination_folder_id")
            or data.get("onedrive_competence_folder_id")
            or data.get("onedrive_documentos_folder_id")
            or data.get("onedrive_client_folder_id")
            or data.get("destination_folder")
        )
        readable = (
            data.get("destination_path_readable")
            or data.get("destination_folder")
            or data.get("onedrive_documentos_folder_web_url")
            or data.get("onedrive_client_folder_web_url")
        )
        if not readable:
            parts = [
                data.get("client_folder_name"),
                data.get("department_folder_name"),
                data.get("competence_folder_name"),
            ]
            readable = "/".join(str(part).strip() for part in parts if str(part or "").strip())
        data["destination_folder_id"] = folder_id
        data["destination_path_readable"] = readable
        if "active" not in data:
            data["active"] = str(data.get("status") or "").lower() in {"active", "activate"}
        return data
