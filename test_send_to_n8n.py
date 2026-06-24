from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from database.supabase_client import get_supabase_client


DEFAULT_BUCKET = "incoming-documents"
DEFAULT_STORAGE_PATH = "uploads/teste.pdf"
DEFAULT_SIGNED_URL_TTL_SECONDS = 600
DEFAULT_WEBHOOK_URL = ""
DEFAULT_NEW_FILE_NAME = "TESTE FINAL - 062026.pdf"
DEFAULT_DESTINATION_FOLDER_ID = "COLE_AQUI_O_ID_DA_PASTA_TESTE_ONEDRIVE"


def create_signed_url(
    bucket: str = DEFAULT_BUCKET,
    storage_path: str = DEFAULT_STORAGE_PATH,
    expires_in_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS,
) -> str:
    normalized_storage_path = storage_path.strip().lstrip("/")
    supabase = get_supabase_client()
    response = supabase.storage.from_(bucket).create_signed_url(
        normalized_storage_path,
        expires_in_seconds,
    )
    signed_url = response.get("signedUrl") or response.get("signedURL")
    if not signed_url:
        raise RuntimeError(f"Supabase nao retornou signed URL: {response}")
    return str(signed_url)


def post_to_n8n(
    webhook_url: str,
    signed_url: str,
    storage_path: str = DEFAULT_STORAGE_PATH,
    new_file_name: str = DEFAULT_NEW_FILE_NAME,
    destination_folder_id: str = DEFAULT_DESTINATION_FOLDER_ID,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    payload = {
        "signed_url": signed_url,
        "storage_path": storage_path.strip().lstrip("/"),
        "new_file_name": new_file_name,
        "destination_folder_id": destination_folder_id,
    }
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read().decode("utf-8", errors="replace")
        return {
            "status_code": response.status,
            "response_body": response_body,
        }


def send_storage_file_to_n8n(
    webhook_url: str,
    bucket: str = DEFAULT_BUCKET,
    storage_path: str = DEFAULT_STORAGE_PATH,
    expires_in_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS,
    new_file_name: str = DEFAULT_NEW_FILE_NAME,
    destination_folder_id: str = DEFAULT_DESTINATION_FOLDER_ID,
) -> dict[str, Any]:
    if not webhook_url:
        raise ValueError("Informe o webhook em N8N_TEST_WEBHOOK_URL ou use --webhook-url.")
    normalized_storage_path = storage_path.strip().lstrip("/")
    signed_url = create_signed_url(
        bucket=bucket,
        storage_path=normalized_storage_path,
        expires_in_seconds=expires_in_seconds,
    )
    n8n_response = post_to_n8n(
        webhook_url=webhook_url,
        signed_url=signed_url,
        storage_path=normalized_storage_path,
        new_file_name=new_file_name,
        destination_folder_id=destination_folder_id,
    )
    return {
        "send_ok": 200 <= int(n8n_response["status_code"]) < 300,
        "bucket": bucket,
        "storage_path": normalized_storage_path,
        "new_file_name": new_file_name,
        "destination_folder_id": destination_folder_id,
        "signed_url": signed_url,
        "n8n_status_code": n8n_response["status_code"],
        "n8n_response_body": n8n_response["response_body"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teste isolado: Supabase Storage signed URL -> webhook n8n.",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.getenv("N8N_TEST_WEBHOOK_URL", DEFAULT_WEBHOOK_URL),
        help="URL do webhook de teste do n8n.",
    )
    parser.add_argument(
        "--bucket",
        default=DEFAULT_BUCKET,
        help=f"Bucket do Supabase Storage. Padrao: {DEFAULT_BUCKET}",
    )
    parser.add_argument(
        "--path",
        default=DEFAULT_STORAGE_PATH,
        help=f"Caminho do arquivo no bucket. Padrao: {DEFAULT_STORAGE_PATH}",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=DEFAULT_SIGNED_URL_TTL_SECONDS,
        help=f"Validade da signed URL em segundos. Padrao: {DEFAULT_SIGNED_URL_TTL_SECONDS}",
    )
    parser.add_argument(
        "--new-file-name",
        default=DEFAULT_NEW_FILE_NAME,
        help=f"Nome final de teste. Padrao: {DEFAULT_NEW_FILE_NAME}",
    )
    parser.add_argument(
        "--destination-folder-id",
        default=DEFAULT_DESTINATION_FOLDER_ID,
        help="ID da pasta destino de teste no OneDrive.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = send_storage_file_to_n8n(
            webhook_url=args.webhook_url,
            bucket=args.bucket,
            storage_path=args.path,
            expires_in_seconds=args.ttl,
            new_file_name=args.new_file_name,
            destination_folder_id=args.destination_folder_id,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["send_ok"] else 1
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "send_ok": False,
                    "bucket": args.bucket,
                    "storage_path": str(args.path).strip().lstrip("/"),
                    "n8n_status_code": exc.code,
                    "error": error_body or str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except (URLError, Exception) as exc:
        print(
            json.dumps(
                {
                    "send_ok": False,
                    "bucket": args.bucket,
                    "storage_path": str(args.path).strip().lstrip("/"),
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
