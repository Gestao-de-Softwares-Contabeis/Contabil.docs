from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.settings import load_settings
from models.document import CoreDocumentResult, UploadedDocument
from models.integration import N8NDispatchResult, StorageUploadResult
from services.storage_service import SupabaseStorageService
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class N8NDispatchService:
    def __init__(
        self,
        storage_service: SupabaseStorageService | None = None,
        webhook_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        settings = load_settings()
        self.storage_service = storage_service
        self.webhook_url = webhook_url if webhook_url is not None else settings.n8n_webhook_url
        self.timeout_seconds = timeout_seconds or settings.n8n_timeout_seconds

    def dispatch(self, document: UploadedDocument, result: CoreDocumentResult) -> N8NDispatchResult:
        if not self.webhook_url:
            return N8NDispatchResult(
                send_ok=False,
                skipped=True,
                error="Webhook n8n nao configurado. Defina N8N_WEBHOOK_URL ou N8N_TEST_WEBHOOK_URL no .env.",
            )

        try:
            storage_service = self.storage_service or SupabaseStorageService()
            storage = storage_service.upload_and_sign(document)
            payload = self.build_payload(result, storage)
            response = self._post(payload)
            return N8NDispatchResult(
                send_ok=200 <= int(response["status_code"]) < 300,
                bucket=storage.bucket,
                storage_path=storage.storage_path,
                new_file_name=result.new_file_name,
                destination_folder_id=result.destination_folder_id,
                signed_url=storage.signed_url,
                n8n_status_code=int(response["status_code"]),
                n8n_response_body=str(response["response_body"]),
                payload=payload,
            )
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.exception(
                "Webhook n8n retornou erro HTTP",
                extra={"ctx_status_code": exc.code, "ctx_file": result.original_file_name},
            )
            return N8NDispatchResult(
                send_ok=False,
                n8n_status_code=exc.code,
                error=error_body or str(exc),
            )
        except (URLError, Exception) as exc:
            logger.exception("Erro ao enviar documento para n8n", extra={"ctx_file": result.original_file_name})
            return N8NDispatchResult(send_ok=False, error=str(exc))

    def build_payload(
        self,
        result: CoreDocumentResult,
        storage: StorageUploadResult,
    ) -> dict[str, object]:
        return {
            "signed_url": storage.signed_url,
            "storage_path": storage.storage_path,
            "bucket": storage.bucket,
            "new_file_name": result.new_file_name,
            "destination_folder_id": result.destination_folder_id,
            "destination_path_readable": result.destination_path_readable,
            "original_file_name": result.original_file_name,
            "extension": result.extension,
            "detected_client_code": result.detected_client_code,
            "detected_client_name": result.detected_client_name,
            "detected_client_cnpj": result.detected_client_cnpj,
            "competence": result.competence,
            "document_type": result.document_type,
            "institution": result.institution,
            "confidence": result.confidence,
        }

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return {
                "status_code": response.status,
                "response_body": response_body,
            }
