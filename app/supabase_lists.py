from __future__ import annotations

from models.collaborator import Collaborator
from services.collaborator_service import CollaboratorService


def safe_active_collaborators() -> tuple[list[Collaborator], str | None]:
    try:
        return CollaboratorService().list_active(), None
    except Exception as exc:
        return [], str(exc)


def collaborator_names(collaborators: list[Collaborator]) -> list[str]:
    return [collaborator.name for collaborator in collaborators]


def collaborator_department(collaborators: list[Collaborator], name: str | None) -> str | None:
    for collaborator in collaborators:
        if collaborator.name == name:
            return collaborator.department
    return None
