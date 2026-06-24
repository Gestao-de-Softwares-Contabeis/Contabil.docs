from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
from typing import Any

from database.supabase_client import get_supabase_client


DEFAULT_BUCKET = "incoming-documents"
DEFAULT_STORAGE_PATH = "uploads/teste.pdf"
DEFAULT_LOCAL_PDF = Path("docs.example") / "FATURA 1.pdf"


def upload_pdf_to_supabase_storage(
    local_pdf_path: Path,
    bucket: str = DEFAULT_BUCKET,
    storage_path: str = DEFAULT_STORAGE_PATH,
) -> dict[str, Any]:
    if not local_pdf_path.exists():
        raise FileNotFoundError(f"Arquivo local nao encontrado: {local_pdf_path}")
    if local_pdf_path.suffix.lower() != ".pdf":
        raise ValueError("Este teste isolado aceita apenas arquivo PDF.")

    normalized_storage_path = storage_path.strip().lstrip("/")
    content_type = mimetypes.guess_type(local_pdf_path.name)[0] or "application/pdf"
    content = local_pdf_path.read_bytes()

    supabase = get_supabase_client()
    response = supabase.storage.from_(bucket).upload(
        normalized_storage_path,
        content,
        file_options={
            "content-type": content_type,
            "upsert": "true",
        },
    )

    return {
        "upload_ok": True,
        "bucket": bucket,
        "storage_path": normalized_storage_path,
        "tamanho": len(content),
        "local_file": str(local_pdf_path),
        "response_path": getattr(response, "path", None),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teste isolado de upload de PDF para Supabase Storage.",
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_LOCAL_PDF),
        help=f"PDF local para enviar. Padrao: {DEFAULT_LOCAL_PDF}",
    )
    parser.add_argument(
        "--bucket",
        default=DEFAULT_BUCKET,
        help=f"Bucket do Supabase Storage. Padrao: {DEFAULT_BUCKET}",
    )
    parser.add_argument(
        "--path",
        default=DEFAULT_STORAGE_PATH,
        help=f"Caminho no bucket. Padrao: {DEFAULT_STORAGE_PATH}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = upload_pdf_to_supabase_storage(
            local_pdf_path=Path(args.file),
            bucket=args.bucket,
            storage_path=args.path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = {
            "upload_ok": False,
            "bucket": args.bucket,
            "storage_path": str(args.path).strip().lstrip("/"),
            "tamanho": None,
            "error": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
