from __future__ import annotations

from models.collaborator import Collaborator
from repositories.collaborator_repository import CollaboratorRepository


class CollaboratorService:
    def __init__(self, repository: CollaboratorRepository | None = None) -> None:
        self.repository = repository or CollaboratorRepository()

    def list_active(self) -> list[Collaborator]:
        return self.repository.list_active()

    def names(self) -> list[str]:
        return [collaborator.name for collaborator in self.list_active()]

    def department_for(self, collaborator_name: str) -> str | None:
        return self.repository.department_for(collaborator_name)
