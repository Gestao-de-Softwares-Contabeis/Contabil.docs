from __future__ import annotations

from models.client import StorageRoute
from repositories.routing_repository import RoutingRepository


class RoutingService:
    def __init__(self, repository: RoutingRepository | None = None) -> None:
        self.repository = repository or RoutingRepository()

    def resolve_route(
        self,
        client_code: str | None,
        department: str | None,
        competence: str | None,
    ) -> StorageRoute | None:
        if not client_code or not department or not competence:
            return None
        return self.repository.get_route_for_document(
            client_code=client_code,
            department=department,
            competence=competence,
        )
