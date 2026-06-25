from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from models.client import Client, StorageRoute
from models.conflict_resolution import ConflictResolutionRequest
from models.document import CoreProcessingStatus, DocumentLogEntry
from models.integration import StorageUploadResult
from models.rule import DocumentRule
from services.conflict_resolution_service import ConflictResolutionService
from services.core_processor import CoreProcessor
from services.identification_service import IdentificationService
from services.routing_service import RoutingService


class MemoryClientRepository:
    def __init__(self, clients: list[Client]) -> None:
        self.clients = clients

    def list_active(self) -> list[Client]:
        return self.clients

    def get_by_client_code(self, client_code: str) -> Client | None:
        return next((client for client in self.clients if client.client_code == client_code), None)


class MemoryRuleRepository:
    def __init__(self, rules: list[DocumentRule]) -> None:
        self.rules = rules
        self.created_count = 0

    def list_active(self) -> list[DocumentRule]:
        return [rule for rule in self.rules if rule.is_active]

    def create(self, rule: DocumentRule) -> DocumentRule:
        self.created_count += 1
        saved = rule.model_copy(update={"id": f"created-{self.created_count}"})
        self.rules.append(saved)
        return saved

    def set_active(self, rule_id: str, active: bool) -> None:
        for index, rule in enumerate(self.rules):
            if rule.id == rule_id:
                self.rules[index] = rule.model_copy(update={"is_active": active, "active": active})
                return
        raise ValueError(f"Regra {rule_id} nao encontrada.")

    def mark_used(self, rule_id: str, current_hits: int) -> None:
        return None


class MemoryRoutingRepository:
    def __init__(self, routes: list[StorageRoute]) -> None:
        self.routes = routes

    def get_route_for_document(
        self,
        client_code: str,
        department: str,
        competence: str,
    ) -> StorageRoute | None:
        return next(
            (
                route
                for route in self.routes
                if route.client_code == client_code
                and route.department == department
                and route.competence == competence
            ),
            None,
        )


class FakeOpenAIService:
    def identify(self, document: object, clients: list[Client]) -> dict[str, object] | None:
        return None


class MemoryLogRepository:
    def __init__(self) -> None:
        self.logs: list[DocumentLogEntry] = []

    def insert(self, entry: DocumentLogEntry) -> DocumentLogEntry:
        self.logs.append(entry)
        return entry


class FakeStorageService:
    def upload_and_sign(self, document: object, storage_path: str | None = None) -> StorageUploadResult:
        return StorageUploadResult(
            upload_ok=True,
            bucket="incoming-documents",
            storage_path=storage_path or "uploads/fake.pdf",
            tamanho=getattr(document, "size_bytes", 0),
            signed_url="https://signed.example/fake.pdf",
            signed_url_ttl_seconds=600,
        )


def client(code: str, name: str, cnpj: str) -> Client:
    return Client(id=f"client-{code}", client_code=code, name=name, cnpj=cnpj)


def route(code: str, competence: str) -> StorageRoute:
    return StorageRoute(
        client_code=code,
        department="contabil",
        competence=competence,
        destination_folder_id=f"folder-{code}-{competence}",
        destination_path_readable=f"/Clientes/{code}/CONTABIL/{competence}",
    )


class ConflictResolutionServiceTest(unittest.TestCase):
    def test_resolve_conflict_creates_rule_deactivates_wrong_rule_and_reprocesses(self) -> None:
        clients = [
            client("147", "RZ COMERCIO DE BIJUTERIAS", "14792240000180"),
            client("231", "OUTRA EMPRESA", "37789606000168"),
        ]
        wrong_rule = DocumentRule(
            id="wrong-bank-rule",
            client_code="231",
            rule_type="bank_account",
            agency="0542",
            account_number="984927",
            is_active=True,
        )
        rule_repository = MemoryRuleRepository([wrong_rule])
        client_repository = MemoryClientRepository(clients)
        routing_repository = MemoryRoutingRepository([route("147", "2026-03"), route("231", "2026-03")])
        identification = IdentificationService(
            client_repository=client_repository,
            rule_repository=rule_repository,
            ai_identifier=FakeOpenAIService(),
        )
        core = CoreProcessor(
            identification_service=identification,
            routing_service=RoutingService(repository=routing_repository),
            storage_service=FakeStorageService(),
        )
        log_repository = MemoryLogRepository()
        service = ConflictResolutionService(
            core_processor=core,
            client_repository=client_repository,
            rule_repository=rule_repository,
            log_repository=log_repository,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "extrato_conflito.txt"
            path.write_text(
                "CNPJ 14.792.240/0001-80 Agencia 0542 Conta 0098492-7 "
                "Periodo: 01/03/2026 - 31/03/2026",
                encoding="utf-8",
            )

            result = service.resolve_and_reprocess(
                ConflictResolutionRequest(
                    file_path=path,
                    department="contabil",
                    selected_client_code="147",
                    created_by="teste",
                    rule_ids_to_deactivate=["wrong-bank-rule"],
                )
            )

        self.assertEqual(result.initial_result.status, CoreProcessingStatus.REVIEW)
        self.assertEqual(result.reprocessed_result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.reprocessed_result.detected_client_code, "147")
        self.assertEqual(result.reprocessed_result.extracted_summary["matched_by"], "manual_override")
        self.assertEqual(result.created_rule_id, "created-1")
        self.assertEqual(result.deactivated_rule_ids, ["wrong-bank-rule"])
        self.assertTrue(result.validation_passed)
        self.assertEqual(rule_repository.rules[0].id, "wrong-bank-rule")
        self.assertFalse(rule_repository.rules[0].is_active)
        self.assertEqual(len(log_repository.logs), 3)


if __name__ == "__main__":
    unittest.main()
