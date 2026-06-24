from __future__ import annotations

import unittest

from models.client import Client, StorageRoute
from models.document import CoreProcessingStatus
from models.integration import N8NDispatchResult
from models.rule import DocumentRule
from services.core_processor import CoreProcessor
from services.identification_service import IdentificationService
from services.routing_service import RoutingService
from utils.normalization import build_client_display_name, detect_institution


class MemoryClientRepository:
    def __init__(self, clients: list[Client]) -> None:
        self.clients = clients

    def list_active(self) -> list[Client]:
        return self.clients


class MemoryRuleRepository:
    def __init__(self, rules: list[DocumentRule] | None = None) -> None:
        self.rules = rules or []

    def list_active(self) -> list[DocumentRule]:
        return self.rules

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
        for route in self.routes:
            if (
                route.client_code == client_code
                and route.department == department
                and route.competence == competence
            ):
                return route
        return None


class FakeOpenAIService:
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result
        self.calls = 0

    def identify(self, document: object, clients: list[Client]) -> dict[str, object] | None:
        self.calls += 1
        return self.result


class FakeN8NDispatchService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def dispatch(self, document: object, result: object) -> N8NDispatchResult:
        self.calls.append((document, result))
        return N8NDispatchResult(
            send_ok=True,
            bucket="incoming-documents",
            storage_path="uploads/fake.pdf",
            new_file_name=getattr(result, "new_file_name", None),
            destination_folder_id=getattr(result, "destination_folder_id", None),
            signed_url="https://signed.example/fake.pdf",
            n8n_status_code=200,
            n8n_response_body="ok",
            payload={
                "signed_url": "https://signed.example/fake.pdf",
                "storage_path": "uploads/fake.pdf",
                "new_file_name": getattr(result, "new_file_name", None),
                "destination_folder_id": getattr(result, "destination_folder_id", None),
            },
        )


def client(
    code: str,
    name: str,
    cnpj: str = "",
    client_id: str | None = None,
) -> Client:
    return Client(
        id=client_id or f"client-{code}",
        client_code=code,
        name=name,
        cnpj=cnpj,
    )


def route(code: str, competence: str) -> StorageRoute:
    return StorageRoute(
        client_code=code,
        department="contabil",
        competence=competence,
        destination_folder_id=f"folder-{code}-{competence}",
        destination_path_readable=f"/Clientes/{code}/CONTABIL/{competence}",
    )


def build_processor(
    clients: list[Client],
    routes: list[StorageRoute],
    rules: list[DocumentRule] | None = None,
    ai_result: dict[str, object] | None = None,
    dispatch_service: FakeN8NDispatchService | None = None,
) -> tuple[CoreProcessor, FakeOpenAIService]:
    fake_ai = FakeOpenAIService(ai_result)
    identification = IdentificationService(
        client_repository=MemoryClientRepository(clients),
        rule_repository=MemoryRuleRepository(rules),
        ai_identifier=fake_ai,
    )
    routing = RoutingService(repository=MemoryRoutingRepository(routes))
    return (
        CoreProcessor(
            identification_service=identification,
            routing_service=routing,
            n8n_dispatch_service=dispatch_service or FakeN8NDispatchService(),
        ),
        fake_ai,
    )


class CoreProcessorTest(unittest.TestCase):
    def test_build_client_display_name_removes_legal_suffix_and_excess(self) -> None:
        self.assertEqual(
            build_client_display_name("RZ COMERCIO DE BIJUTERIAS E ACESSORIOS FEMININOS LTDA - ME", "147"),
            "RZ COMERCIO DE BIJUTERIAS",
        )

    def test_detect_institution_prioritizes_banco_do_brasil(self) -> None:
        institution = detect_institution("Pagamento na CAIXA Fatura OUROCARD bb.com.br", "FATURA 1.pdf")

        self.assertEqual(institution, "Banco do Brasil")

    def test_card_invoice_competence_is_previous_month_from_due_date(self) -> None:
        acme = client("001", "ACME LTDA", "12345678000199")
        processor, fake_ai = build_processor([acme], [route("001", "2026-03")])

        result = processor.process_file(
            filename="fatura_acme.txt",
            content=(
                "Fatura do cartao credito cliente codigo 001 "
                "vencimento 10/04/2026 total R$ 100,00"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.document_type, "fatura_cartao_credito")
        self.assertEqual(result.competence, "2026-03")
        self.assertEqual(fake_ai.calls, 0)

    def test_investment_competence_is_previous_month_when_only_issue_date_exists(self) -> None:
        acme = client("001", "ACME LTDA", "12345678000199")
        processor, _ = build_processor([acme], [route("001", "2026-05")])

        result = processor.process_file(
            filename="investimentos_acme.txt",
            content=(
                "Posicao detalhada de operacoes Cliente codigo 001 "
                "Consulta 05/06/2026 CDB-DI"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.document_type, "posicao_investimentos")
        self.assertEqual(result.competence, "2026-05")

    def test_financial_report_does_not_apply_previous_month_rule(self) -> None:
        acme = client("001", "ACME LTDA", "12345678000199")
        processor, _ = build_processor([acme], [route("001", "2026-05")])

        result = processor.process_file(
            filename="extrato_financeiro.txt",
            content=(
                "Extrato financeiro cliente codigo 001 "
                "Data movimento 04/05/2026 pagamentos recebimentos cartao"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.document_type, "relatorio_financeiro")
        self.assertEqual(result.competence, "2026-05")

    def test_bank_account_rule_identifies_client(self) -> None:
        acme = client("001", "ACME LTDA")
        rule = DocumentRule(
            client_code="001",
            rule_type="bank_account",
            bank_name="Itau",
            agency="0542",
            account_number="984927",
            created_by="teste",
        )
        processor, fake_ai = build_processor([acme], [route("001", "2026-03")], rules=[rule])

        result = processor.process_file(
            filename="extrato_0542_984927.txt",
            content="Banco Itau Agencia 0542 Conta 0098492-7 Periodo: 01/03/2026 - 31/03/2026".encode(
                "utf-8"
            ),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.detected_client_code, "001")
        self.assertEqual(result.extracted_summary["matched_by"], "bank_account")
        self.assertEqual(fake_ai.calls, 0)

    def test_bank_account_without_rule_returns_error_with_suggestion(self) -> None:
        processor, fake_ai = build_processor([], [])

        result = processor.process_file(
            filename="extrato_0542_984927.txt",
            content="Agencia 0542 Conta 0098492-7 Periodo: 01/03/2026 - 31/03/2026".encode(
                "utf-8"
            ),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.IDENTIFICATION_ERROR)
        self.assertEqual(result.suggested_rule_type, "bank_account")
        self.assertEqual(result.extracted_agency, "542")
        self.assertEqual(result.extracted_account_number, "984927")
        self.assertEqual(fake_ai.calls, 1)

    def test_single_partner_rule_identifies_client(self) -> None:
        acme = client("001", "ACME LTDA")
        rule = DocumentRule(
            client_code="001",
            rule_type="partner_name",
            rule_value="Vanessa Cunha Rezende",
            created_by="teste",
        )
        processor, fake_ai = build_processor([acme], [route("001", "2026-03")], rules=[rule])

        result = processor.process_file(
            filename="relatorio_socio.txt",
            content="Relatorio financeiro Vanessa Cunha Rezende Data movimento 15/03/2026".encode(
                "utf-8"
            ),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.detected_client_code, "001")
        self.assertEqual(result.extracted_summary["matched_by"], "partner_name")
        self.assertEqual(fake_ai.calls, 0)

    def test_abbreviated_partner_name_identifies_client(self) -> None:
        acme = client("001", "ACME LTDA")
        rule = DocumentRule(
            client_code="001",
            rule_type="partner_name",
            rule_value="WALESKA DE OLIVEIRA GONCALVES REZENDE",
            created_by="teste",
        )
        processor, fake_ai = build_processor([acme], [route("001", "2026-03")], rules=[rule])

        result = processor.process_file(
            filename="fatura_socio.txt",
            content="Fatura do cartao Waleska O G Rezende vencimento 16/04/2026".encode(
                "utf-8"
            ),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.detected_client_code, "001")
        self.assertEqual(result.extracted_summary["matched_by"], "partner_name")
        self.assertEqual(fake_ai.calls, 0)

    def test_partner_name_in_multiple_clients_returns_review(self) -> None:
        acme = client("001", "ACME LTDA")
        beta = client("002", "BETA LTDA")
        rules = [
            DocumentRule(client_code="001", rule_type="partner_name", rule_value="Vanessa Cunha Rezende"),
            DocumentRule(client_code="002", rule_type="partner_name", rule_value="Vanessa Cunha Rezende"),
        ]
        processor, fake_ai = build_processor([acme, beta], [route("001", "2026-03"), route("002", "2026-03")], rules=rules)

        result = processor.process_file(
            filename="relatorio_socio.txt",
            content="Relatorio financeiro Vanessa Cunha Rezende Data movimento 15/03/2026".encode(
                "utf-8"
            ),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.REVIEW)
        self.assertIn("Socio encontrado em multiplos clientes", result.review_reason or "")
        self.assertEqual(fake_ai.calls, 0)

    def test_conflict_between_cnpj_and_bank_account_returns_review(self) -> None:
        client_147 = client("147", "RZ COMERCIO", "14792240000180")
        client_231 = client("231", "EFFECTIVE", "37789606000168")
        bank_rule = DocumentRule(
            client_code="231",
            rule_type="bank_account",
            agency="0542",
            account_number="984927",
        )
        processor, fake_ai = build_processor(
            [client_147, client_231],
            [route("147", "2026-03"), route("231", "2026-03")],
            rules=[bank_rule],
        )

        result = processor.process_file(
            filename="extrato_conflito.txt",
            content=(
                "CNPJ 14.792.240/0001-80 Agencia 0542 Conta 0098492-7 "
                "Periodo: 01/03/2026 - 31/03/2026"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.REVIEW)
        self.assertIn("Conflito entre sinais fortes", result.review_reason or "")
        self.assertEqual(fake_ai.calls, 0)

    def test_manual_override_rule_resolves_existing_conflict(self) -> None:
        client_147 = client("147", "RZ COMERCIO", "14792240000180")
        client_231 = client("231", "EFFECTIVE", "37789606000168")
        rules = [
            DocumentRule(
                client_code="231",
                rule_type="bank_account",
                agency="0542",
                account_number="984927",
            ),
            DocumentRule(
                client_code="147",
                rule_type="manual_override",
                rule_value="extrato_conflito.txt",
                match_mode="contains",
            ),
        ]
        processor, fake_ai = build_processor(
            [client_147, client_231],
            [route("147", "2026-03"), route("231", "2026-03")],
            rules=rules,
        )

        result = processor.process_file(
            filename="extrato_conflito.txt",
            content=(
                "CNPJ 14.792.240/0001-80 Agencia 0542 Conta 0098492-7 "
                "Periodo: 01/03/2026 - 31/03/2026"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.detected_client_code, "147")
        self.assertEqual(result.extracted_summary["matched_by"], "manual_override")
        self.assertEqual(fake_ai.calls, 0)

    def test_ready_document_is_uploaded_and_sent_to_n8n(self) -> None:
        acme = client("001", "ACME LTDA", "12345678000199")
        dispatch = FakeN8NDispatchService()
        processor, fake_ai = build_processor(
            [acme],
            [route("001", "2026-03")],
            dispatch_service=dispatch,
        )

        result = processor.process_file(
            filename="fatura_acme.txt",
            content=(
                "Fatura do cartao credito cliente codigo 001 "
                "vencimento 10/04/2026 total R$ 100,00"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(len(dispatch.calls), 1)
        self.assertTrue(result.n8n_dispatch["send_ok"])
        self.assertEqual(result.n8n_dispatch["storage_path"], "uploads/fake.pdf")
        self.assertEqual(result.n8n_dispatch["payload"]["destination_folder_id"], result.destination_folder_id)
        self.assertEqual(fake_ai.calls, 0)

    def test_openai_does_not_override_deterministic_institution(self) -> None:
        acme = client("001", "ACME LTDA", "12345678000199")
        processor, fake_ai = build_processor(
            [acme],
            [route("001", "2026-03")],
            ai_result={
                "cliente_codigo": "001",
                "tipo_documento": "fatura_cartao_credito",
                "instituicao": "Caixa Economica",
                "score": 0.95,
            },
        )

        result = processor.process_file(
            filename="fatura_acme.txt",
            content=(
                "Fatura OUROCARD bb.com.br vencimento 10/04/2026 total R$ 100,00"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.READY_TO_SEND)
        self.assertEqual(result.institution, "Banco do Brasil")
        self.assertEqual(fake_ai.calls, 1)

    def test_review_document_is_not_sent_to_n8n(self) -> None:
        client_147 = client("147", "RZ COMERCIO", "14792240000180")
        client_231 = client("231", "EFFECTIVE", "37789606000168")
        dispatch = FakeN8NDispatchService()
        processor, _ = build_processor(
            [client_147, client_231],
            [route("147", "2026-03"), route("231", "2026-03")],
            rules=[
                DocumentRule(
                    client_code="231",
                    rule_type="bank_account",
                    agency="0542",
                    account_number="984927",
                )
            ],
            dispatch_service=dispatch,
        )

        result = processor.process_file(
            filename="extrato_conflito.txt",
            content=(
                "CNPJ 14.792.240/0001-80 Agencia 0542 Conta 0098492-7 "
                "Periodo: 01/03/2026 - 31/03/2026"
            ).encode("utf-8"),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.REVIEW)
        self.assertEqual(len(dispatch.calls), 0)
        self.assertEqual(result.n8n_dispatch, {})

    def test_identification_error_document_is_not_sent_to_n8n(self) -> None:
        dispatch = FakeN8NDispatchService()
        processor, _ = build_processor([], [], dispatch_service=dispatch)

        result = processor.process_file(
            filename="extrato_sem_cliente.txt",
            content="Agencia 0542 Conta 0098492-7 Periodo: 01/03/2026 - 31/03/2026".encode(
                "utf-8"
            ),
            department="contabil",
        )

        self.assertEqual(result.status, CoreProcessingStatus.IDENTIFICATION_ERROR)
        self.assertEqual(len(dispatch.calls), 0)
        self.assertEqual(result.n8n_dispatch, {})


if __name__ == "__main__":
    unittest.main()
