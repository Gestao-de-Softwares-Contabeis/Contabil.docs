from __future__ import annotations

from database.supabase_client import get_supabase_client
from models.collaborator import Collaborator
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class CollaboratorRepository:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def list_active(self) -> list[Collaborator]:
        try:
            response = (
                self.client.table("collaborators")
                .select("*")
                .eq("status", "active")
                .order("name")
                .execute()
            )
            return [Collaborator.model_validate(row) for row in response.data or []]
        except Exception:
            logger.exception("Erro ao listar colaboradores ativos")
            raise

    def department_for(self, collaborator_name: str) -> str | None:
        for collaborator in self.list_active():
            if collaborator.name == collaborator_name:
                return collaborator.department
        return None
