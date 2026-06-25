from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.settings import get_n8n_webhook_debug_info, get_n8n_webhook_url, load_settings
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
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds or settings.n8n_timeout_seconds

    def dispatch(self, document: UploadedDocument, result: CoreDocumentResult) -> N8NDispatchResult:
        try:
            webhook_url = self._webhook_url()
            webhook_debug = self._webhook_debug_info()
        except ValueError as exc:
            return N8NDispatchResult(
                send_ok=False,
                skipped=True,
                error=str(exc),
            )

        try:
            storage_service = self.storage_service or SupabaseStorageService()
            storage = storage_service.upload_and_sign(document)
            return self.dispatch_analyzed(result, storage, webhook_url=webhook_url, webhook_debug=webhook_debug)
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

    def dispatch_analyzed(
        self,
        result: CoreDocumentResult,
        storage: StorageUploadResult | None = None,
        webhook_url: str | None = None,
        webhook_debug: dict[str, str] | None = None,
    ) -> N8NDispatchResult:
        try:
            selected_webhook_url = webhook_url or self._webhook_url()
            selected_webhook_debug = webhook_debug or self._webhook_debug_info()
        except ValueError as exc:
            return N8NDispatchResult(
                send_ok=False,
                skipped=True,
                error=str(exc),
            )

        payload: dict[str, object] = {}
        try:
            storage_data = storage or StorageUploadResult.model_validate(result.storage_upload)
            payload = self.build_payload(result, storage_data)
            response = self._post(payload, selected_webhook_url)
            return N8NDispatchResult(
                send_ok=200 <= int(response["status_code"]) < 300,
                bucket=storage_data.bucket,
                storage_path=storage_data.storage_path,
                new_file_name=result.new_file_name,
                destination_folder_id=result.destination_folder_id,
                signed_url=storage_data.signed_url,
                n8n_status_code=int(response["status_code"]),
                n8n_response_body=str(response["response_body"]),
                payload=payload,
                webhook_variable=selected_webhook_debug.get("variable"),
                webhook_endpoint=selected_webhook_debug.get("endpoint"),
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
                payload=payload,
                webhook_variable=selected_webhook_debug.get("variable"),
                webhook_endpoint=selected_webhook_debug.get("endpoint"),
            )
        except (URLError, Exception) as exc:
            logger.exception("Erro ao enviar documento analisado para n8n", extra={"ctx_file": result.original_file_name})
            return N8NDispatchResult(
                send_ok=False,
                error=str(exc),
                payload=payload,
                webhook_variable=selected_webhook_debug.get("variable"),
                webhook_endpoint=selected_webhook_debug.get("endpoint"),
            )

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

    def _webhook_url(self) -> str:
        return self.webhook_url.strip() if self.webhook_url else get_n8n_webhook_url()

    def _webhook_debug_info(self) -> dict[str, str]:
        if self.webhook_url:
            return {"variable": "argumento", "endpoint": self._safe_endpoint(self.webhook_url)}
        return get_n8n_webhook_debug_info()

    def _safe_endpoint(self, url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return f"{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path

    def _post(self, payload: dict[str, object], webhook_url: str) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            webhook_url,
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
