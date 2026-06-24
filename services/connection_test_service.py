from __future__ import annotations

from dataclasses import dataclass

from database.supabase_client import get_supabase_client
from utils.structured_logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class SupabaseConnectionTestResult:
    ok: bool
    clients_count: int | None
    rules_count: int | None
    routes_count: int | None
    collaborators_count: int | None
    message: str


class SupabaseConnectionTestService:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def test_connection(self) -> SupabaseConnectionTestResult:
        counts: dict[str, int | None] = {
            "clients": None,
            "document_rules": None,
            "storage_folder_map": None,
            "collaborators": None,
        }
        errors: list[str] = []

        for table_name in counts:
            try:
                counts[table_name] = self._count_table(table_name)
            except Exception as exc:
                logger.exception("Erro no teste de conexao Supabase", extra={"ctx_table": table_name})
                errors.append(f"{table_name}: {exc}")

        return SupabaseConnectionTestResult(
            ok=not errors,
            clients_count=counts["clients"],
            rules_count=counts["document_rules"],
            routes_count=counts["storage_folder_map"],
            collaborators_count=counts["collaborators"],
            message="Conexao OK" if not errors else self._format_error_message(errors),
        )

    def _count_table(self, table_name: str) -> int:
        response = self.client.table(table_name).select("id", count="exact").limit(0).execute()
        return int(response.count or 0)

    def _format_error_message(self, errors: list[str]) -> str:
        message = "Falha ao consultar: " + " | ".join(errors)
        if "permission denied" in message.lower() or "42501" in message:
            message += " | Rode database/grants.sql no SQL Editor do Supabase."
        return message
