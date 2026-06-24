from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.supabase_client import get_supabase_client
from models.rule import DocumentRule
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class RuleRepository:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def list_active(self) -> list[DocumentRule]:
        try:
            response = (
                self.client.table("active_document_rules")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            return [DocumentRule.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar regras ativas")
            raise

    def list_all(self, limit: int = 1000) -> list[DocumentRule]:
        try:
            response = (
                self.client.table("document_rules")
                .select("*")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return [DocumentRule.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar regras")
            raise

    def create(self, rule: DocumentRule) -> DocumentRule:
        payload = rule.model_dump(mode="json", exclude_none=True)
        payload.pop("id", None)
        payload.pop("client_id", None)
        payload.pop("client_name", None)
        payload.pop("pattern", None)
        payload.pop("institution", None)
        payload.pop("active", None)
        payload.pop("hits_count", None)
        try:
            response = self.client.table("document_rules").insert(payload).execute()
            return DocumentRule.model_validate((response.data or [payload])[0])
        except Exception:
            logger.exception("Erro ao criar regra", extra={"ctx_client_code": rule.client_code})
            raise

    def set_active(self, rule_id: str, active: bool) -> None:
        try:
            (
                self.client.table("document_rules")
                .update({"is_active": active})
                .eq("id", rule_id)
                .execute()
            )
        except Exception:
            logger.exception("Erro ao alterar status da regra", extra={"ctx_rule_id": rule_id})
            raise

    def mark_used(self, rule_id: str, current_hits: int) -> None:
        try:
            (
                self.client.table("document_rules")
                .update(
                    {
                        "last_used_at": datetime.now(timezone.utc).isoformat(),
                        "hit_count": current_hits + 1,
                    }
                )
                .eq("id", rule_id)
                .execute()
            )
        except Exception:
            logger.exception("Erro ao registrar uso da regra", extra={"ctx_rule_id": rule_id})
            raise
