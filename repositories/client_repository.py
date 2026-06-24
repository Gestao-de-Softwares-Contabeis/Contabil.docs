from __future__ import annotations

from typing import Any

from database.supabase_client import get_supabase_client
from models.client import Client
from utils.normalization import normalize_text, only_digits
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class ClientRepository:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def list_active(self) -> list[Client]:
        try:
            response = (
                self.client.table("clients")
                .select("*")
                .in_("status", ["active", "activate"])
                .order("client_name")
                .execute()
            )
            return [Client.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar clientes ativos")
            raise

    def get_by_client_code(self, client_code: str) -> Client | None:
        try:
            response = (
                self.client.table("clients")
                .select("*")
                .eq("client_code", client_code)
                .in_("status", ["active", "activate"])
                .limit(1)
                .execute()
            )
            rows: list[dict[str, Any]] = response.data or []
            return Client.model_validate(rows[0]) if rows else None
        except Exception:
            logger.exception("Erro ao buscar cliente por codigo", extra={"ctx_client_code": client_code})
            raise

    def get_by_id(self, client_id: str) -> Client | None:
        try:
            response = (
                self.client.table("clients")
                .select("*")
                .eq("id", client_id)
                .in_("status", ["active", "activate"])
                .limit(1)
                .execute()
            )
            rows: list[dict[str, Any]] = response.data or []
            return Client.model_validate(rows[0]) if rows else None
        except Exception:
            logger.exception("Erro ao buscar cliente", extra={"ctx_client_id": client_id})
            raise

    def create_client(
        self,
        name: str,
        cnpj: str | None,
        aliases: list[str],
        bank_accounts: list[dict[str, str]],
    ) -> Client:
        payload = {
            "client_name": name.strip(),
            "client_cnpj": only_digits(cnpj),
            "status": "active",
        }
        try:
            response = self.client.table("clients").insert(payload).execute()
            return Client.model_validate((response.data or [payload])[0])
        except Exception:
            logger.exception("Erro ao criar cliente", extra={"ctx_client_name": name})
            raise
