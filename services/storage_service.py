from __future__ import annotations

import mimetypes

from app.settings import load_settings
from database.supabase_client import get_supabase_client
from models.document import UploadedDocument
from models.integration import StorageUploadResult
from utils.normalization import sanitize_filename_part
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class SupabaseStorageService:
    def __init__(
        self,
        bucket: str | None = None,
        upload_prefix: str | None = None,
        signed_url_ttl_seconds: int | None = None,
    ) -> None:
        settings = load_settings()
        self.client = get_supabase_client()
        self.bucket = bucket or settings.supabase_storage_bucket
        self.upload_prefix = (upload_prefix or settings.supabase_storage_upload_prefix).strip("/")
        self.signed_url_ttl_seconds = signed_url_ttl_seconds or settings.storage_signed_url_ttl_seconds

    def upload_and_sign(
        self,
        document: UploadedDocument,
        storage_path: str | None = None,
    ) -> StorageUploadResult:
        normalized_path = storage_path.strip().lstrip("/") if storage_path else self.build_storage_path(document)
        content_type = mimetypes.guess_type(document.original_filename)[0] or "application/octet-stream"
        try:
            response = self.client.storage.from_(self.bucket).upload(
                normalized_path,
                document.content,
                file_options={
                    "content-type": content_type,
                    "upsert": "true",
                },
            )
            signed_response = self.client.storage.from_(self.bucket).create_signed_url(
                normalized_path,
                self.signed_url_ttl_seconds,
            )
            signed_url = signed_response.get("signedUrl") or signed_response.get("signedURL")
            if not signed_url:
                raise RuntimeError(f"Supabase nao retornou signed URL: {signed_response}")
            return StorageUploadResult(
                upload_ok=True,
                bucket=self.bucket,
                storage_path=normalized_path,
                tamanho=document.size_bytes,
                signed_url=str(signed_url),
                signed_url_ttl_seconds=self.signed_url_ttl_seconds,
                response_path=getattr(response, "path", None),
            )
        except Exception:
            logger.exception(
                "Erro ao subir arquivo no Supabase Storage",
                extra={"ctx_bucket": self.bucket, "ctx_storage_path": normalized_path},
            )
            raise

    def delete_object(self, storage_path: str) -> bool:
        normalized_path = storage_path.strip().lstrip("/")
        if not normalized_path:
            return False
        try:
            self.client.storage.from_(self.bucket).remove([normalized_path])
            return True
        except Exception:
            logger.exception(
                "Erro ao remover arquivo do Supabase Storage",
                extra={"ctx_bucket": self.bucket, "ctx_storage_path": normalized_path},
            )
            return False

    def build_storage_path(self, document: UploadedDocument) -> str:
        safe_name = sanitize_filename_part(document.original_filename, "documento")
        hash_prefix = document.file_hash[:12] if document.file_hash else "sem_hash"
        if self.upload_prefix:
            return f"{self.upload_prefix}/{hash_prefix}-{safe_name}"
        return f"{hash_prefix}-{safe_name}"
