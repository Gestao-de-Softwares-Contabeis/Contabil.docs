from __future__ import annotations

import unittest

from models.document_checklist import CHECKLIST_RECEIVED, ClientDocumentChecklist, DocumentChecklistStatus
from models.document_queue import DocumentQueueItem
from services.checklist_service import ChecklistService


class FakeChecklistRepository:
    def __init__(self, items: list[ClientDocumentChecklist]) -> None:
        self.items = items
        self.received: list[tuple[ClientDocumentChecklist, DocumentQueueItem]] = []

    def list_active_for_client(self, client_code: str) -> list[ClientDocumentChecklist]:
        return [item for item in self.items if item.client_code == client_code and item.is_active]

    def list_checklist(self, client_code: str | None = None) -> list[ClientDocumentChecklist]:
        return [item for item in self.items if not client_code or item.client_code == client_code]

    def mark_received(
        self,
        checklist_item: ClientDocumentChecklist,
        queue_item: DocumentQueueItem,
    ) -> DocumentChecklistStatus:
        self.received.append((checklist_item, queue_item))
        return DocumentChecklistStatus(
            checklist_id=checklist_item.id,
            client_code=queue_item.client_code or checklist_item.client_code,
            competence=queue_item.competence or "",
            document_type=checklist_item.document_type,
            institution=checklist_item.institution,
            status=CHECKLIST_RECEIVED,
            matched_document_queue_id=queue_item.id,
            uploaded_by=queue_item.uploaded_by,
            auto_matched=True,
        )


class FakePersistentChecklistRepository:
    def __init__(self, items: list[ClientDocumentChecklist]) -> None:
        self.items = items
        self.statuses: list[DocumentChecklistStatus] = []

    def list_active_for_client(self, client_code: str) -> list[ClientDocumentChecklist]:
        return [item for item in self.items if item.client_code == client_code and item.is_active]

    def list_checklist(self, client_code: str | None = None) -> list[ClientDocumentChecklist]:
        return [item for item in self.items if not client_code or item.client_code == client_code]

    def mark_received(
        self,
        checklist_item: ClientDocumentChecklist,
        queue_item: DocumentQueueItem,
    ) -> DocumentChecklistStatus:
        status = DocumentChecklistStatus(
            checklist_id=checklist_item.id,
            client_code=queue_item.client_code or checklist_item.client_code,
            competence=queue_item.competence or "",
            document_type=checklist_item.document_type,
            file_extension=queue_item.extension,
            institution=queue_item.institution,
            status=CHECKLIST_RECEIVED,
            matched_document_queue_id=queue_item.id,
            uploaded_by=queue_item.uploaded_by,
            auto_matched=True,
        )
        self.statuses.append(status)
        return status


class ChecklistServiceTest(unittest.TestCase):
    def test_marks_received_when_type_and_institution_match(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="extrato_bancario",
                    file_extension="ofx",
                    institution="SICOOB",
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence="2026-06",
            document_type="extrato_bancario",
            extension="ofx",
            institution="sicoob",
            uploaded_by="Alessandro",
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].status, CHECKLIST_RECEIVED)
        self.assertEqual(matches[0].uploaded_by, "Alessandro")

    def test_file_extension_must_match_when_checklist_defines_it(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="extrato_bancario",
                    file_extension="ofx",
                    institution="SICOOB",
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence="2026-06",
            document_type="extrato_bancario",
            extension="pdf",
            institution="SICOOB",
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(matches, [])
        self.assertEqual(repo.received, [])

    def test_document_name_pattern_filters_same_type_and_bank(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="147",
                    document_type="fatura_cartao_credito",
                    file_extension="pdf",
                    institution="Banco do Brasil",
                    document_name_pattern="ourocard",
                ),
                ClientDocumentChecklist(
                    id="check-2",
                    client_code="147",
                    document_type="fatura_cartao_credito",
                    file_extension="pdf",
                    institution="Banco do Brasil",
                    document_name_pattern="conta corrente",
                ),
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            original_file_name="FATURA 1.pdf",
            new_file_name="RZ - Banco do Brasil - 062026 - fatura_cartao_credito.pdf",
            client_code="147",
            competence="2026-06",
            document_type="fatura_cartao_credito",
            extension="pdf",
            institution="Banco do Brasil",
            payload_json={"extracted_summary": {"text_preview": "Fatura Ourocard vencimento 10/07/2026"}},
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(len(matches), 1)
        self.assertEqual(repo.received[0][0].id, "check-1")

    def test_missing_required_document_fields_does_not_mark(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="relatorio_financeiro",
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence=None,
            document_type="relatorio_financeiro",
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(matches, [])
        self.assertEqual(repo.received, [])

    def test_sent_document_marks_checklist_status_as_received(self) -> None:
        repo = FakePersistentChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="extrato_bancario",
                    file_extension="pdf",
                    institution="Sicoob",
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence="2026-06",
            document_type="extrato_bancario",
            extension="pdf",
            institution="SICOOB",
            uploaded_by="Alessandro",
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(len(matches), 1)
        self.assertEqual(repo.statuses[0].status, CHECKLIST_RECEIVED)
        self.assertEqual(repo.statuses[0].matched_document_queue_id, "queue-1")
        self.assertEqual(repo.statuses[0].uploaded_by, "Alessandro")
        self.assertEqual(repo.statuses[0].file_extension, "pdf")

    def test_ofx_without_institution_matches_type_and_extension(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="extrato_bancario",
                    file_extension="ofx",
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence="2026-05",
            document_type="extrato_bancario",
            extension="ofx",
            institution=None,
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(len(matches), 1)
        self.assertEqual(repo.received[0][0].id, "check-1")

    def test_xlsx_without_institution_matches_type_and_extension(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="extrato_bancario",
                    file_extension="xlsx",
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence="2026-05",
            document_type="extrato_bancario",
            extension="xlsx",
            institution=None,
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(len(matches), 1)
        self.assertEqual(repo.received[0][0].id, "check-1")

    def test_investment_income_matches_even_when_checklist_institution_is_empty(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="rendimentos_investimentos",
                    file_extension="pdf",
                    institution=None,
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence="2026-05",
            document_type="rendimentos_investimentos",
            extension="pdf",
            institution="Sicoob",
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(len(matches), 1)
        self.assertEqual(repo.received[0][0].id, "check-1")

    def test_divergent_institution_does_not_block_when_type_and_extension_match(self) -> None:
        repo = FakeChecklistRepository(
            [
                ClientDocumentChecklist(
                    id="check-1",
                    client_code="210",
                    document_type="extrato_bancario",
                    file_extension="pdf",
                    institution="Banco do Brasil",
                )
            ]
        )
        service = ChecklistService(repo)  # type: ignore[arg-type]
        queue_item = DocumentQueueItem(
            id="queue-1",
            file_hash="hash",
            client_code="210",
            competence="2026-05",
            document_type="extrato_bancario",
            extension="pdf",
            institution="Sicoob",
        )

        matches = service.mark_document_received(queue_item)

        self.assertEqual(len(matches), 1)
        self.assertEqual(repo.received[0][0].id, "check-1")

    def test_monthly_matrix_uses_fixed_checklist_and_sent_documents(self) -> None:
        service = ChecklistService(FakeChecklistRepository([]))  # type: ignore[arg-type]
        checklist_items = [
            ClientDocumentChecklist(
                id="check-1",
                client_code="210",
                document_type="extrato_bancario",
                file_extension="pdf",
                institution="Sicoob",
                is_active=True,
            ),
            ClientDocumentChecklist(
                id="check-2",
                client_code="210",
                document_type="relatorio_financeiro",
                file_extension="xlsx",
                institution="Conta Azul",
                is_active=False,
            ),
        ]
        sent_documents = [
            DocumentQueueItem(
                id="queue-1",
                file_hash="hash",
                client_code="210",
                competence="2026-06",
                document_type="extrato_bancario",
                extension="pdf",
                institution="SICOOB",
                status="ENVIADO",
            )
        ]

        matrix = service.build_monthly_matrix(checklist_items, sent_documents, ["2026-05", "2026-06"])

        self.assertEqual(len(matrix), 2)
        self.assertEqual(matrix[0]["document_type"], "extrato_bancario")
        self.assertEqual(matrix[0]["2026-05"], "PENDENTE")
        self.assertEqual(matrix[0]["2026-06"], "RECEBIDO")
        self.assertEqual(matrix[1]["document_type"], "relatorio_financeiro")
        self.assertEqual(matrix[1]["2026-06"], "PENDENTE")

    def test_monthly_matrix_uses_received_status_or_sent_document(self) -> None:
        service = ChecklistService(FakeChecklistRepository([]))  # type: ignore[arg-type]
        checklist_items = [
            ClientDocumentChecklist(
                id="check-1",
                client_code="210",
                document_type="extrato_bancario",
                file_extension="ofx",
                is_active=True,
            )
        ]
        received_statuses = [
            DocumentChecklistStatus(
                checklist_id="check-1",
                client_code="210",
                competence="2026-05",
                document_type="extrato_bancario",
                file_extension="ofx",
                status=CHECKLIST_RECEIVED,
            )
        ]

        matrix = service.build_monthly_matrix(
            checklist_items,
            sent_documents=[],
            competences=["2026-05"],
            received_statuses=received_statuses,
        )

        self.assertEqual(matrix[0]["2026-05"], "RECEBIDO")


if __name__ == "__main__":
    unittest.main()
