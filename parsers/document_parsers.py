from __future__ import annotations

import io
from abc import ABC, abstractmethod
from pathlib import Path

from app.settings import load_settings
from models.document import UploadedDocument
from utils.normalization import (
    extract_bank_account_signals,
    extract_cnpjs,
    extract_document_dates,
    extract_terms_candidates,
    get_extension,
    sha256_bytes,
)
from utils.structured_logging import get_logger


logger = get_logger(__name__)


class ParserError(RuntimeError):
    pass


def decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="ignore")


class BaseDocumentParser(ABC):
    @abstractmethod
    def extract_text(self, content: bytes, filename: str) -> str:
        raise NotImplementedError


class PdfParser(BaseDocumentParser):
    def extract_text(self, content: bytes, filename: str) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            parts: list[str] = []
            for index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text:
                    parts.append(f"--- pagina {index} ---\n{page_text}")
            return "\n".join(parts)
        except Exception as exc:
            logger.exception("Falha ao ler PDF", extra={"ctx_filename": filename})
            raise ParserError(f"Falha ao ler PDF {filename}: {exc}") from exc


class OfxParser(BaseDocumentParser):
    def extract_text(self, content: bytes, filename: str) -> str:
        return decode_bytes(content)


class CsvParser(BaseDocumentParser):
    def extract_text(self, content: bytes, filename: str) -> str:
        raw_text = decode_bytes(content)
        try:
            import pandas as pd

            dataframe = pd.read_csv(io.StringIO(raw_text), sep=None, engine="python", dtype=str)
            return dataframe.fillna("").to_csv(index=False, sep=";")
        except Exception:
            logger.info("CSV mantido como texto bruto", extra={"ctx_filename": filename})
            return raw_text


class SpreadsheetParser(BaseDocumentParser):
    def extract_text(self, content: bytes, filename: str) -> str:
        try:
            import pandas as pd

            sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=str)
            parts: list[str] = []
            for sheet_name, dataframe in sheets.items():
                parts.append(f"--- planilha {sheet_name} ---")
                parts.append(dataframe.fillna("").to_csv(index=False, sep=";"))
            return "\n".join(parts)
        except Exception as exc:
            logger.exception("Falha ao ler planilha", extra={"ctx_filename": filename})
            raise ParserError(f"Falha ao ler planilha {filename}: {exc}") from exc


class TxtParser(BaseDocumentParser):
    def extract_text(self, content: bytes, filename: str) -> str:
        return decode_bytes(content)


class DocumentParserService:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.parsers: dict[str, BaseDocumentParser] = {
            "pdf": PdfParser(),
            "ofx": OfxParser(),
            "csv": CsvParser(),
            "xls": SpreadsheetParser(),
            "xlsx": SpreadsheetParser(),
            "txt": TxtParser(),
        }

    def parse(self, filename: str, content: bytes) -> UploadedDocument:
        extension = get_extension(filename)
        parser = self.parsers.get(extension)
        if not parser:
            raise ParserError(f"Formato nao suportado: {extension}")

        text = parser.extract_text(content, filename)
        if len(text) > self.settings.max_text_chars_to_store:
            text = text[: self.settings.max_text_chars_to_store]

        return UploadedDocument(
            original_filename=filename,
            extension=extension,
            size_bytes=len(content),
            content=content,
            extracted_text=text,
            file_hash=sha256_bytes(content),
        )

    def parse_path(self, file_path: str | Path) -> UploadedDocument:
        path = Path(file_path)
        return self.parse(path.name, path.read_bytes())

    def build_summary(self, document: UploadedDocument) -> dict[str, object]:
        preview = document.extracted_text[:500].replace("\n", " ").strip()
        dates = extract_document_dates(document.original_filename, document.extracted_text)
        bank_account = extract_bank_account_signals(document.original_filename, document.extracted_text)
        return {
            "file_hash": document.file_hash,
            "file_size_bytes": document.size_bytes,
            "extracted_text_length": len(document.extracted_text),
            "text_preview": preview,
            "detected_cnpjs": extract_cnpjs(document.extracted_text),
            "extracted_dates": {
                "issue_date": dates["issue_date"].isoformat() if dates["issue_date"] else None,
                "due_date": dates["due_date"].isoformat() if dates["due_date"] else None,
                "period_start": dates["period_start"].isoformat() if dates["period_start"] else None,
                "period_end": dates["period_end"].isoformat() if dates["period_end"] else None,
            },
            "bank_account": bank_account,
            "terms_candidates": extract_terms_candidates(document.original_filename, document.extracted_text),
        }
