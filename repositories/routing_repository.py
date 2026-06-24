from __future__ import annotations

from typing import Any

from database.supabase_client import get_supabase_client
from models.client import StorageRoute
from utils.normalization import normalize_competence, normalize_text
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class RoutingRepository:
    def __init__(self) -> None:
        self.client = get_supabase_client()

    def get_destination_folder(self, client_id: str, document_type: str) -> str | None:
        try:
            response = (
                self.client.table("document_routing_lookup")
                .select("destination_folder")
                .eq("client_id", client_id)
                .eq("document_type", document_type)
                .limit(1)
                .execute()
            )
            rows: list[dict[str, Any]] = response.data or []
            return rows[0].get("destination_folder") if rows else None
        except Exception:
            logger.exception(
                "Erro ao buscar pasta de destino",
                extra={"ctx_client_id": client_id, "ctx_document_type": document_type},
            )
            raise

    def get_route_for_document(
        self,
        client_code: str,
        department: str,
        competence: str,
    ) -> StorageRoute | None:
        try:
            response = (
                self.client.table("document_routing_lookup")
                .select("*")
                .eq("client_code", client_code)
                .eq("department", department)
                .eq("competence", competence)
                .execute()
            )
            rows: list[dict[str, Any]] = response.data or []
            return self._select_best_route(rows, department, competence)
        except Exception:
            logger.exception(
                "Erro ao buscar rota por codigo/departamento/competencia",
                extra={
                    "ctx_client_code": client_code,
                    "ctx_department": department,
                    "ctx_competence": competence,
                },
            )
            raise

    def _select_best_route(
        self,
        rows: list[dict[str, Any]],
        department: str,
        competence: str,
    ) -> StorageRoute | None:
        if not rows:
            return None

        wanted_department = normalize_text(department)
        wanted_competence = normalize_competence(competence)
        candidates: list[StorageRoute] = []
        for row in rows:
            route = StorageRoute.model_validate(row)
            route_department = normalize_text(route.department)
            route_competence = normalize_competence(route.competence)
            if wanted_department and route_department and route_department != wanted_department:
                continue
            if wanted_competence and route_competence and route_competence != wanted_competence:
                continue
            candidates.append(route)

        if not candidates:
            return None

        exact = [
            item
            for item in candidates
            if normalize_text(item.department) == wanted_department
            and normalize_competence(item.competence) == wanted_competence
        ]
        if exact:
            return exact[0]

        department_match = [
            item for item in candidates if normalize_text(item.department) == wanted_department
        ]
        if department_match:
            return department_match[0]

        return candidates[0]

    def upsert_route(
        self,
        client_id: str,
        document_type: str,
        destination_folder: str,
        created_by: str,
    ) -> StorageRoute:
        try:
            existing = (
                self.client.table("storage_folder_map")
                .select("*")
                .eq("client_id", client_id)
                .eq("document_type", document_type)
                .eq("active", True)
                .limit(1)
                .execute()
            )
            rows: list[dict[str, Any]] = existing.data or []
            if rows:
                route_id = rows[0]["id"]
                response = (
                    self.client.table("storage_folder_map")
                    .update({"destination_folder": destination_folder, "updated_by": created_by})
                    .eq("id", route_id)
                    .execute()
                )
            else:
                response = (
                    self.client.table("storage_folder_map")
                    .insert(
                        {
                            "client_id": client_id,
                            "document_type": document_type,
                            "destination_folder": destination_folder,
                            "created_by": created_by,
                            "active": True,
                        }
                    )
                    .execute()
                )
            return StorageRoute.model_validate((response.data or [])[0])
        except Exception:
            logger.exception(
                "Erro ao salvar rota",
                extra={"ctx_client_id": client_id, "ctx_document_type": document_type},
            )
            raise
